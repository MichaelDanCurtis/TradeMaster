"use client";

import type { ReactNode } from "react";

export function InfoModal({
  children,
  onClose,
  title
}: {
  children: ReactNode;
  onClose: () => void;
  title: string;
}) {
  return (
    <div className="info-modal-backdrop" role="presentation" onClick={onClose}>
      <section
        aria-label={title}
        aria-modal="true"
        className="info-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="info-modal-header">
          <h2>{title}</h2>
          <button aria-label={`Close ${title}`} className="icon-button" onClick={onClose} type="button">
            x
          </button>
        </header>
        <div className="info-modal-body">{children}</div>
      </section>
    </div>
  );
}
