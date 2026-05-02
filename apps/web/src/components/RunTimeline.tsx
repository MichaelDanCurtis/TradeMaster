import type { RunEvent } from "@/lib/types";

export function RunTimeline({ events }: { events: RunEvent[] }) {
  return (
    <div className="run-timeline">
      {events.length === 0 ? (
        <p className="muted">No run events yet.</p>
      ) : (
        events.map((event) => (
          <article className="timeline-event" key={`${event.run_id}-${event.sequence}`}>
            <div className="event-type">{event.type}</div>
            <div className="event-message">{event.message}</div>
            {event.node ? <div className="event-node">{event.node}</div> : null}
          </article>
        ))
      )}
    </div>
  );
}
