/**
 * Keeps only the newest of overlapping async requests (QA-01).
 *
 * Each `start()` returns a ticket and voids (and aborts) the previous one;
 * `cancel()` voids the current one, e.g. when the user changes the input the
 * request was for. A late answer is applied only while its ticket is current.
 */
export interface Ticket {
  readonly signal: AbortSignal;
  isCurrent(): boolean;
}

export class LatestRequest {
  private id = 0;
  private controller: AbortController | null = null;

  cancel(): void {
    this.id += 1;
    this.controller?.abort();
    this.controller = null;
  }

  start(): Ticket {
    this.cancel();
    const mine = this.id;
    const controller = new AbortController();
    this.controller = controller;
    return { signal: controller.signal, isCurrent: () => this.id === mine };
  }
}
