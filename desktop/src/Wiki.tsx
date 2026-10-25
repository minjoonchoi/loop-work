import { useEffect, useRef } from "react";
import { api } from "./bridge";
import type { Wiki as WikiType } from "./types";
import "./editor/markdown.js";
import "./editor/editor.js";
declare global {
  interface Window {
    LoopEditor: any;
    LoopMarkdown: any;
    LoopDesktop?: any;
  }
}
export const editors = new Map<string, any>();
export function Wiki({
  kind,
  id,
  projectId,
}: {
  kind: "task" | "project";
  id: string;
  projectId: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const key = kind + ":" + id + ":" + projectId;
  useEffect(() => {
    let cancelled = false;
    const endpoint =
      "/api/" +
      (kind === "task" ? "tasks" : "projects") +
      "/" +
      encodeURIComponent(id) +
      "/wiki?project_id=" +
      encodeURIComponent(projectId);
    async function load() {
      try {
        let editor = editors.get(key);
        if (!editor) {
          const record = await api<WikiType>(endpoint);
          if (cancelled) return;
          editor = new window.LoopEditor.WikiEditor(
            { ...record, kind },
            {
              save: (payload: unknown) => api(endpoint, payload),
              fetchLatest: () => api(endpoint),
              onSaved: () => window.dispatchEvent(new Event("wiki-saved")),
            },
          );
          editors.set(key, editor);
        }
        if (cancelled) return;
        host.current?.replaceChildren(editor.element || editor.root);
        editor.resume();
      } catch (e) {
        if (!cancelled && host.current)
          host.current.textContent = (e as Error).message;
      }
    }
    load();
    const timer = setInterval(async () => {
      const editor = editors.get(key);
      if (!editor || editor.composing || document.visibilityState !== "visible")
        return;
      try {
        editor.observe(await api(endpoint));
      } catch (e) {
        editor.report((e as Error).message, true);
      }
    }, 5000);
    return () => {
      clearInterval(timer);
      cancelled = true;
      editors.get(key)?.suspend();
    };
  }, [key, kind, id, projectId]);
  return <div ref={host} className="wiki-host" />;
}
