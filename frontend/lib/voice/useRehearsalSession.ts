"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AgentSocket } from "./agentSocket";
import { parseDelivery } from "./delivery";
import type { ChatRequest, ChatResponse, Turn } from "./types";
import { useSpeechRecognition } from "./useSpeechRecognition";
import { useVoicePlayback } from "./useVoicePlayback";

export type SessionPhase =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  /** Mic is open but what you say is a note to the persona, not a line in the scene. */
  | "directing";

export interface RehearsalSession {
  phase: SessionPhase;
  turns: Turn[];
  /** Live partial transcript of whoever is currently talking. */
  interim: string;
  error: string | null;
  micSupported: boolean;
  lastMemoryWrite: ChatResponse["memoryWrite"] | null;
  start: () => void;
  end: () => void;
  /** Cuts the persona off and opens the mic for a correction. */
  interrupt: () => void;
  /** Leaves director mode without recording a note. */
  cancelInterrupt: () => void;
  /** Types a line or note instead of speaking it — for testing without a mic. */
  submit: (kind: "line" | "note", text: string) => void;
  /** Speaks a fixed line. Isolates audio from everything upstream of it. */
  testVoice: () => void;
}

export interface UseRehearsalSessionOptions {
  sessionId: string;
  personaId: string;
}

let turnSeq = 0;
const nextId = () => `t${++turnSeq}`;

export function useRehearsalSession({
  sessionId,
  personaId,
}: UseRehearsalSessionOptions): RehearsalSession {
  const [phase, setPhase] = useState<SessionPhase>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastMemoryWrite, setLastMemoryWrite] = useState<ChatResponse["memoryWrite"] | null>(null);

  const playback = useVoicePlayback();

  // Event handlers fire from browser callbacks that captured an old render, so
  // anything they read lives in a ref.
  const phaseRef = useRef<SessionPhase>("idle");
  const turnsRef = useRef<Turn[]>([]);
  const setPhaseSafe = useCallback((next: SessionPhase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);
  const appendTurn = useCallback((turn: Turn) => {
    turnsRef.current = [...turnsRef.current, turn];
    setTurns(turnsRef.current);
  }, []);

  const micRef = useRef<{ start: () => void; stop: () => void }>({
    start: () => {},
    stop: () => {},
  });

  /** Last thing the persona said, so Turbo can carry prosody into the next line. */
  const previousLineRef = useRef<string | undefined>(undefined);

  /** True between start() and end(). Typed input works outside that window. */
  const startedRef = useRef(false);

  /** Numbers each turn, so a cancelled one can tell it has been replaced. */
  const turnCountRef = useRef(0);

  /** One WebSocket to the voice agent for the whole rehearsal. */
  const socketRef = useRef<AgentSocket | null>(null);
  const agent = useCallback(() => (socketRef.current ??= new AgentSocket()), []);
  useEffect(() => () => socketRef.current?.close(), []);

  /** Stops whatever the persona is saying, on the speaker and on the server. */
  const silence = useCallback(() => {
    turnCountRef.current += 1;
    socketRef.current?.cancel();
    playback.stop();
  }, [playback]);

  const send = useCallback(
    async (kind: "line" | "note", text: string) => {
      const thisTurn = ++turnCountRef.current;
      const replaced = () => turnCountRef.current !== thisTurn;
      setPhaseSafe("thinking");
      setError(null);

      const payload: ChatRequest = {
        sessionId,
        personaId,
        kind,
        text,
        history: turnsRef.current,
      };

      /** Shows the reply in the transcript; returns the spoken line. */
      const showReply = (data: ChatResponse) => {
        if (data.memoryWrite) setLastMemoryWrite(data.memoryWrite);
        if (data.degraded) setError(data.degraded);
        const { delivery, line } = parseDelivery(data.reply ?? "");
        if (!line) throw new Error("The persona returned an empty line");
        appendTurn({
          id: nextId(),
          role: "persona",
          text: line,
          delivery,
          retake: kind === "note",
          at: Date.now(),
        });
        return line;
      };

      try {
        const turn = await agent().startTurn(payload).catch(() => null);

        if (turn) {
          // WebSocket: audio starts playing while Claude is still writing.
          const playing = playback.play(turn.audio, () => setPhaseSafe("speaking"));
          const line = showReply(await turn.reply);
          await playing;
          previousLineRef.current = line;
        } else {
          // Fallback if the socket can't connect: two HTTP calls.
          const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          if (!res.ok) {
            const detail = await res.json().catch(() => ({ error: res.statusText }));
            throw new Error(detail.error || `Chat failed (${res.status})`);
          }
          const data: ChatResponse = await res.json();
          const line = showReply(data);
          setPhaseSafe("speaking");
          await playback.speak(data.reply, previousLineRef.current);
          previousLineRef.current = line;
        }

        // Hand the floor back, unless the user interrupted while it spoke.
        if (replaced()) return;
        if (phaseRef.current === "speaking" || phaseRef.current === "thinking") settle();
      } catch (err) {
        // Cut off on purpose: a newer turn, a director note, or the session ended.
        if (replaced() || phaseRef.current === "directing" || phaseRef.current === "idle") return;
        const message = err instanceof Error ? err.message : "Something went wrong";
        setError(message);
        settle();
      }

      /** Reopen the mic, but only if this is a real rehearsal and not a typed test. */
      function settle() {
        if (startedRef.current) {
          setPhaseSafe("listening");
          micRef.current.start();
        } else {
          setPhaseSafe("idle");
        }
      }
    },
    [agent, appendTurn, personaId, playback, sessionId, setPhaseSafe],
  );

  const handleFinalTranscript = useCallback(
    (transcript: string) => {
      const mode = phaseRef.current;
      if (mode !== "listening" && mode !== "directing") return;

      micRef.current.stop();

      if (mode === "directing") {
        appendTurn({ id: nextId(), role: "director", text: transcript, at: Date.now() });
        void send("note", transcript);
      } else {
        appendTurn({ id: nextId(), role: "user", text: transcript, at: Date.now() });
        void send("line", transcript);
      }
    },
    [appendTurn, send],
  );

  const mic = useSpeechRecognition({ onFinal: handleFinalTranscript });
  micRef.current = { start: mic.start, stop: mic.stop };

  const start = useCallback(() => {
    setError(null);
    startedRef.current = true;
    setPhaseSafe("listening");
    mic.start();
  }, [mic, setPhaseSafe]);

  const end = useCallback(() => {
    startedRef.current = false;
    mic.stop();
    silence();
    setPhaseSafe("idle");
  }, [mic, silence, setPhaseSafe]);

  /** Same path a spoken utterance takes, minus the microphone. */
  const submit = useCallback(
    (kind: "line" | "note", text: string) => {
      const trimmed = text.trim();
      if (!trimmed || phaseRef.current === "thinking") return;
      mic.stop();
      silence();
      appendTurn({
        id: nextId(),
        role: kind === "note" ? "director" : "user",
        text: trimmed,
        at: Date.now(),
      });
      void send(kind, trimmed);
    },
    [appendTurn, mic, silence, send],
  );

  /** Straight to the speaker — proves the ElevenLabs half in isolation. */
  const testVoice = useCallback(() => {
    setError(null);
    void playback.speak("[slow|flat|clipped] Thirty percent. Or I walk.");
  }, [playback]);

  /**
   * Director Interrupt: cut the line off mid-word and take a note.
   * Stopping the audio first is the point — you correct her while she is
   * still saying the wrong thing, the way a director actually would.
   */
  const interrupt = useCallback(() => {
    if (phaseRef.current === "idle" || phaseRef.current === "directing") return;
    silence();
    mic.stop();
    setPhaseSafe("directing");
    mic.start();
  }, [mic, silence, setPhaseSafe]);

  const cancelInterrupt = useCallback(() => {
    if (phaseRef.current !== "directing") return;
    mic.stop();
    setPhaseSafe("listening");
    mic.start();
  }, [mic, setPhaseSafe]);

  // Hold D to cut in, release to deliver the note. Held rather than toggled so
  // there is no chance of leaving the mic in the wrong mode on camera.
  useEffect(() => {
    const isTyping = (target: EventTarget | null) =>
      target instanceof HTMLElement &&
      (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "d" || event.repeat || isTyping(event.target)) return;
      if (phaseRef.current === "idle") return;
      event.preventDefault();
      interrupt();
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "d" || isTyping(event.target)) return;
      if (phaseRef.current !== "directing") return;
      event.preventDefault();
      // The utterance is still being transcribed; handleFinalTranscript takes it
      // from here. Nothing to do but let go.
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [interrupt]);

  return {
    phase,
    turns,
    interim: mic.interim,
    error: error ?? mic.error ?? playback.error,
    micSupported: mic.supported,
    lastMemoryWrite,
    start,
    end,
    interrupt,
    cancelInterrupt,
    submit,
    testVoice,
  };
}
