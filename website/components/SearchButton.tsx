"use client";
import { useEffect, useState } from "react";

export function openSearch() {
  window.dispatchEvent(new CustomEvent("ohx:search"));
}

export function SearchButton() {
  const [mac, setMac] = useState(true);
  useEffect(() => setMac(/Mac|iPhone|iPad/.test(navigator.platform)), []);
  return (
    <button type="button" className="search-trigger" onClick={openSearch} aria-label="Search the documentation" aria-keyshortcuts={mac ? "Meta+K" : "Control+K"}>
      <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path d="m10.5 10.5 3.5 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
      <span className="label">Search docs</span>
      <kbd>{mac ? "⌘" : "Ctrl"} K</kbd>
    </button>
  );
}
