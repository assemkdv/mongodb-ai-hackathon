import type { ChatRequest, ChatResponse } from "./types";

/**
 * The browser's end of the WebSocket to the voice agent (FastAPI /ws/session).
 *
 * One connection per rehearsal, reused for every turn. For each turn the
 * server streams back:
 *   - binary frames: MP3 audio, played as soon as the first one lands
 *   - {"type": "reply"}: the line's text (for the transcript)
 *   - {"type": "done"}: audio finished
 * and the browser can send {"type": "cancel"} at any moment (barge-in).
 */

export const AGENT_SOCKET_URL =
  process.env.NEXT_PUBLIC_BACKEND_WS_URL || "ws://localhost:3001/ws/session";

export interface SocketTurn {
  /** MP3 chunks as they arrive from the server. */
  audio: ReadableStream<Uint8Array>;
  /** Resolves with the reply text once Claude has finished the line. */
  reply: Promise<ChatResponse>;
}

interface ActiveTurn {
  audio: ReadableStreamDefaultController<Uint8Array>;
  resolveReply: (data: ChatResponse) => void;
  rejectReply: (error: Error) => void;
}

export class AgentSocket {
  private socket: WebSocket | null = null;
  private turn: ActiveTurn | null = null;

  constructor(private readonly url: string = AGENT_SOCKET_URL) {}

  /** Sends one turn. Rejects only if the socket can't be opened at all. */
  async startTurn(payload: ChatRequest): Promise<SocketTurn> {
    const socket = await this.connect();
    this.cancel(); // a new turn always replaces one that is still playing

    let turn!: ActiveTurn;
    const reply = new Promise<ChatResponse>((resolveReply, rejectReply) => {
      turn = { audio: null!, resolveReply, rejectReply };
    });
    reply.catch(() => {}); // the caller handles it; avoid an unhandled-rejection warning
    const audio = new ReadableStream<Uint8Array>({
      start: (controller) => {
        turn.audio = controller;
      },
    });

    this.turn = turn;
    socket.send(JSON.stringify({ type: "turn", ...payload }));
    return { audio, reply };
  }

  /** Barge-in: stop the server generating and close this turn's audio. */
  cancel(): void {
    if (!this.turn) return;
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "cancel" }));
    }
    this.finish(new Error("cancelled"));
  }

  close(): void {
    this.cancel();
    this.socket?.close();
    this.socket = null;
  }

  private connect(): Promise<WebSocket> {
    if (this.socket?.readyState === WebSocket.OPEN) return Promise.resolve(this.socket);

    return new Promise((resolve, reject) => {
      const socket = new WebSocket(this.url);
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        this.socket = socket;
        resolve(socket);
      };
      socket.onerror = () => reject(new Error(`Could not connect to ${this.url}`));
      socket.onclose = () => {
        if (this.socket === socket) this.socket = null;
        this.finish(new Error("Connection to the voice agent was lost"));
      };
      socket.onmessage = (event) => this.onMessage(event);
    });
  }

  private onMessage(event: MessageEvent) {
    const turn = this.turn;
    if (!turn) return; // late audio from a cancelled turn

    if (event.data instanceof ArrayBuffer) {
      turn.audio.enqueue(new Uint8Array(event.data));
      return;
    }

    const message = JSON.parse(event.data);
    if (message.type === "reply") {
      const { type: _type, ...data } = message;
      turn.resolveReply(data as ChatResponse);
    } else if (message.type === "done") {
      this.finish();
    } else if (message.type === "error") {
      this.finish(new Error(message.error));
    }
  }

  /** Ends the current turn: closes its audio stream, settles its reply. */
  private finish(error?: Error) {
    const turn = this.turn;
    if (!turn) return;
    this.turn = null;
    try {
      turn.audio.close();
    } catch {
      // already closed
    }
    // No effect if the reply already arrived.
    turn.rejectReply(error ?? new Error("The turn ended without a reply"));
  }
}
