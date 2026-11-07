import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import { mediaUrl } from "./api";
import type { ImageReference } from "./generationTypes";
import "./prompt-editor.css";

export type PromptEditorHandle = {
  focus(): void;
  setSelection(start: number, end?: number): void;
};

type Props = {
  value: string;
  references: ImageReference[];
  disabled?: boolean;
  placeholder: string;
  onChange: (value: string, caret: number) => void;
  onFocus: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
  onCompositionStart: () => void;
  onCompositionEnd: () => void;
  onReferenceHover?: (reference: ImageReference, rect: DOMRect | null) => void;
};

type SelectionOffsets = { start: number; end: number };
type Entry = { node: Node; start: number; end: number; atomic?: boolean; boundaries?: number[] };
type Snapshot = { value: string; entries: Entry[] };
type HistoryEntry = SelectionOffsets & { value: string };
const chipSelector = "[data-prompt-reference]";

// Read the editable DOM rather than innerText: a chip represents its complete
// @title, regardless of its thumbnail, visual truncation, or browser selection.
function readEditor(root: HTMLElement): Snapshot {
  let value = "";
  const entries: Entry[] = [];
  function visit(node: Node) {
    const entry: Entry = { node, start: value.length, end: value.length };
    entries.push(entry);
    if (node.nodeType === Node.TEXT_NODE) value += node.textContent || "";
    else if (node instanceof HTMLElement && node.matches(chipSelector)) {
      value += node.dataset.promptText || "";
      entry.atomic = true;
    } else if (node instanceof HTMLBRElement) {
      // Chromium leaves a single placeholder BR after deleting all content.
      if (!node.hasAttribute("data-prompt-tail") && !(node.parentNode === root && root.childNodes.length === 1)) value += "\n";
    } else {
      entry.boundaries = [];
      Array.from(node.childNodes).forEach((child, index) => {
        if (index > 0 && child instanceof HTMLElement && /^(DIV|P|LI)$/.test(child.tagName) && !value.endsWith("\n")) value += "\n";
        entry.boundaries!.push(value.length);
        visit(child);
      });
      entry.boundaries.push(value.length);
    }
    entry.end = value.length;
  }
  visit(root);
  return { value, entries };
}

function pointOffset(snapshot: Snapshot, node: Node, offset: number): number {
  const entry = snapshot.entries.find(item => item.node === node);
  if (entry) {
    if (node.nodeType === Node.TEXT_NODE) return Math.min(entry.end, entry.start + offset);
    if (entry.atomic) return offset ? entry.end : entry.start;
    return entry.boundaries?.[Math.min(offset, entry.boundaries.length - 1)] ?? entry.start;
  }
  const chip = snapshot.entries.find(item => item.atomic && item.node.contains(node));
  return chip?.end ?? snapshot.value.length;
}

function selectionOffsets(root: HTMLElement, snapshot = readEditor(root)): SelectionOffsets | null {
  const selection = window.getSelection();
  if (!selection?.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
  return { start: pointOffset(snapshot, range.startContainer, range.startOffset), end: pointOffset(snapshot, range.endContainer, range.endOffset) };
}

function restoreSelection(root: HTMLElement, offsets: SelectionOffsets) {
  const snapshot = readEditor(root);
  const point = (offset: number): [Node, number] => {
    offset = Math.max(0, Math.min(snapshot.value.length, offset));
    // Text nodes on both sides of each chip make both caret positions editable.
    const text = snapshot.entries.find(entry => entry.node.nodeType === Node.TEXT_NODE && entry.start <= offset && entry.end >= offset);
    if (text) return [text.node, offset - text.start];
    const chip = snapshot.entries.find(entry => entry.atomic && entry.start <= offset && entry.end >= offset);
    if (chip) {
      const index = Array.prototype.indexOf.call(root.childNodes, chip.node);
      return [root, index + (offset - chip.start >= (chip.end - chip.start) / 2 ? 1 : 0)];
    }
    return [root, root.childNodes.length];
  };
  const range = document.createRange();
  range.setStart(...point(offsets.start));
  range.setEnd(...point(offsets.end));
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

function remapSelection(previous: string, next: string, selection: SelectionOffsets): SelectionOffsets {
  let prefix = 0;
  while (prefix < previous.length && prefix < next.length && previous[prefix] === next[prefix]) prefix++;
  let suffix = 0;
  while (suffix < previous.length - prefix && suffix < next.length - prefix && previous[previous.length - suffix - 1] === next[next.length - suffix - 1]) suffix++;
  const move = (offset: number) => offset < prefix ? offset : offset >= previous.length - suffix ? Math.max(prefix, offset + next.length - previous.length) : next.length - suffix;
  return { start: move(selection.start), end: move(selection.end) };
}

const PromptEditor = forwardRef<PromptEditorHandle, Props>(function PromptEditor(props, forwardedRef) {
  const root = useRef<HTMLDivElement>(null);
  const latest = useRef(props);
  latest.current = props;
  const composing = useRef(false);
  const plain = useRef(props.value);
  const savedSelection = useRef<SelectionOffsets>({ start: props.value.length, end: props.value.length });
  const history = useRef<HistoryEntry[]>([{ value: props.value, ...savedSelection.current }]);
  const historyIndex = useRef(0);
  const hovered = useRef<{ reference: ImageReference; element: HTMLElement } | null>(null);
  const renderingKey = useRef("");
  const beforeInput = useRef<(event: InputEvent) => void>(() => undefined);

  const clearHover = () => {
    if (hovered.current) latest.current.onReferenceHover?.(hovered.current.reference, null);
    hovered.current = null;
  };

  function render(value: string, selection?: SelectionOffsets) {
    const element = root.current;
    if (!element || composing.current) return;
    const unique = new Map<string, ImageReference>();
    latest.current.references.forEach(reference => { if (reference.title && !unique.has(reference.title)) unique.set(reference.title, reference); });
    const references = [...unique.values()].sort((a, b) => b.title.length - a.title.length);
    const key = JSON.stringify([value, references.map(reference => [reference.title, reference.version_id])]);
    if (key !== renderingKey.current || readEditor(element).value !== value) {
      clearHover();
      const fragment = document.createDocumentFragment();
      let cursor = 0;
      let textStart = 0;
      while (cursor < value.length) {
        const reference = value[cursor] === "@" ? references.find(item => value.startsWith(`@${item.title}`, cursor)) : undefined;
        if (!reference) { cursor++; continue; }
        fragment.append(document.createTextNode(value.slice(textStart, cursor)));
        const chip = document.createElement("span");
        chip.className = "prompt-editor-reference";
        chip.contentEditable = "false";
        chip.dataset.promptReference = reference.version_id;
        chip.dataset.promptText = `@${reference.title}`;
        chip.setAttribute("aria-label", `引用图片：${reference.title}`);
        chip.title = reference.title;
        const thumbnail = document.createElement("img");
        thumbnail.src = mediaUrl(reference.version_id,reference.media_type==="audio"?"waveform":"thumbnail");
        thumbnail.alt = "";
        thumbnail.draggable = false;
        const name = document.createElement("span");
        name.textContent = `@${reference.title}`;
        chip.append(thumbnail, name);
        fragment.append(chip);
        cursor += reference.title.length + 1;
        textStart = cursor;
      }
      fragment.append(document.createTextNode(value.slice(textStart)));
      if (value.endsWith("\n")) {
        const tail = document.createElement("br");
        tail.setAttribute("data-prompt-tail", "");
        fragment.append(tail);
      }
      element.replaceChildren(fragment);
      renderingKey.current = key;
    }
    element.dataset.empty = String(!value.length);
    if (selection) restoreSelection(element, selection);
  }

  function rememberSelection() {
    if (!root.current) return;
    const selection = selectionOffsets(root.current);
    if (!selection) return;
    savedSelection.current = selection;
    if (history.current[historyIndex.current]?.value === plain.current) Object.assign(history.current[historyIndex.current], selection);
  }

  function pushHistory(value: string, selection: SelectionOffsets) {
    if (history.current[historyIndex.current]?.value === value) {
      Object.assign(history.current[historyIndex.current], selection);
      return;
    }
    history.current = history.current.slice(0, historyIndex.current + 1);
    history.current.push({ value, ...selection });
    if (history.current.length > 150) history.current.shift();
    historyIndex.current = history.current.length - 1;
  }

  function commit(value: string, selection: SelectionOffsets, record = true) {
    const changed = plain.current !== value;
    plain.current = value;
    savedSelection.current = selection;
    if (record) pushHistory(value, selection);
    render(value, selection);
    if (changed) latest.current.onChange(value, selection.end);
  }

  function input() {
    if (!root.current || composing.current || latest.current.disabled) return;
    const snapshot = readEditor(root.current);
    commit(snapshot.value, selectionOffsets(root.current, snapshot) || savedSelection.current);
  }

  function replaceSelection(text: string, explicit?: SelectionOffsets) {
    if (!root.current || latest.current.disabled) return;
    const snapshot = readEditor(root.current);
    const selection = explicit || selectionOffsets(root.current, snapshot) || savedSelection.current;
    // Selections crossing an atomic chip replace the whole token.
    let { start, end } = selection;
    snapshot.entries.filter(entry => entry.atomic).forEach(entry => {
      if (start > entry.start && start < entry.end) start = entry.start;
      if (end > entry.start && end < entry.end) end = entry.end;
    });
    const value = snapshot.value.slice(0, start) + text + snapshot.value.slice(end);
    commit(value, { start: start + text.length, end: start + text.length });
  }

  function deleteChip(backward: boolean): boolean {
    if (!root.current) return false;
    const snapshot = readEditor(root.current);
    const selection = selectionOffsets(root.current, snapshot);
    if (!selection) return false;
    if (selection.start !== selection.end) {
      if (snapshot.entries.some(entry => entry.atomic && selection.start < entry.end && selection.end > entry.start)) {
        replaceSelection("", selection);
        return true;
      }
      return false;
    }
    const chip = snapshot.entries.find(entry => entry.atomic && (backward ? entry.end === selection.start : entry.start === selection.start));
    if (!chip) return false;
    replaceSelection("", { start: chip.start, end: chip.end });
    return true;
  }

  function travelHistory(direction: number) {
    const index = historyIndex.current + direction;
    if (index < 0 || index >= history.current.length) return;
    historyIndex.current = index;
    const entry = history.current[index];
    commit(entry.value, { start: entry.start, end: entry.end }, false);
  }

  beforeInput.current = event => {
    if (composing.current || event.isComposing || latest.current.disabled) return;
    if (event.inputType === "insertParagraph" || event.inputType === "insertLineBreak") {
      event.preventDefault();
      replaceSelection("\n");
    } else if (event.inputType === "deleteContentBackward" || event.inputType === "deleteContentForward") {
      if (deleteChip(event.inputType === "deleteContentBackward")) event.preventDefault();
    } else if (event.inputType === "historyUndo" || event.inputType === "historyRedo") {
      event.preventDefault();
      travelHistory(event.inputType === "historyUndo" ? -1 : 1);
    }
  };

  useImperativeHandle(forwardedRef, () => ({
    focus() {
      if (latest.current.disabled || !root.current) return;
      // Updating references while the picker owns focus replaces the DOM.
      // Preserve the saved caret before onFocus can observe that reset range.
      const selection = { ...savedSelection.current };
      root.current.focus({ preventScroll: true });
      if (!composing.current) {
        restoreSelection(root.current, selection);
        rememberSelection();
      }
    },
    setSelection(start, end = start) {
      savedSelection.current = { start, end };
      if (root.current && !composing.current) restoreSelection(root.current, savedSelection.current);
    },
  }), []);

  useLayoutEffect(() => {
    if (!root.current || composing.current) return;
    const focused = document.activeElement === root.current;
    const selection = selectionOffsets(root.current) || savedSelection.current;
    const next = plain.current === props.value ? selection : remapSelection(plain.current, props.value, selection);
    if (plain.current !== props.value) {
      pushHistory(props.value, next);
      plain.current = props.value;
    }
    savedSelection.current = next;
    render(props.value, focused ? next : undefined);
  }, [props.value, props.references]);

  useLayoutEffect(() => {
    const element = root.current;
    const listener = (event: Event) => beforeInput.current(event as InputEvent);
    element?.addEventListener("beforeinput", listener);
    return () => { element?.removeEventListener("beforeinput", listener); clearHover(); };
  }, []);

  return <div
    ref={root}
    className="prompt-editor nodrag nowheel"
    role="textbox"
    aria-label="图片生成描述"
    aria-multiline="true"
    aria-disabled={!!props.disabled}
    aria-placeholder={props.placeholder}
    data-placeholder={props.placeholder}
    contentEditable={!props.disabled}
    suppressContentEditableWarning
    spellCheck={false}
    tabIndex={props.disabled ? -1 : 0}
    onInput={input}
    onFocus={() => { latest.current.onFocus(); rememberSelection(); }}
    onBlur={() => { rememberSelection(); clearHover(); }}
    onMouseUp={rememberSelection}
    onKeyUp={rememberSelection}
    onCompositionStart={() => { rememberSelection(); composing.current = true; latest.current.onCompositionStart(); }}
    onCompositionEnd={() => { composing.current = false; latest.current.onCompositionEnd(); input(); }}
    onKeyDown={event => {
      event.stopPropagation();
      rememberSelection();
      latest.current.onKeyDown(event);
      if (event.defaultPrevented || composing.current || event.nativeEvent.isComposing || latest.current.disabled) return;
      const key = event.key.toLowerCase();
      if ((event.ctrlKey || event.metaKey) && !event.altKey && (key === "z" || key === "y")) {
        event.preventDefault();
        travelHistory(key === "y" || event.shiftKey ? 1 : -1);
      } else if (event.key === "Enter") {
        event.preventDefault();
        replaceSelection("\n");
      } else if (!event.ctrlKey && !event.metaKey && !event.altKey && (event.key === "Backspace" || event.key === "Delete")) {
        if (deleteChip(event.key === "Backspace")) event.preventDefault();
      }
    }}
    onPaste={event => {
      event.preventDefault();
      if (composing.current || props.disabled) return;
      replaceSelection(event.clipboardData.getData("text/plain").replace(/\r\n?/g, "\n"));
    }}
    onCopy={event => {
      if (!root.current) return;
      const snapshot = readEditor(root.current);
      const selection = selectionOffsets(root.current, snapshot);
      if (!selection || selection.start === selection.end) return;
      event.preventDefault();
      event.clipboardData.setData("text/plain", snapshot.value.slice(selection.start, selection.end));
    }}
    onCut={event => {
      if (!root.current || props.disabled || composing.current) return;
      const snapshot = readEditor(root.current);
      const selection = selectionOffsets(root.current, snapshot);
      if (!selection || selection.start === selection.end) return;
      event.preventDefault();
      event.clipboardData.setData("text/plain", snapshot.value.slice(selection.start, selection.end));
      replaceSelection("", selection);
    }}
    onDragOver={event => event.preventDefault()}
    onDrop={event => event.preventDefault()}
    onMouseOver={event => {
      const element = (event.target as Element).closest<HTMLElement>(chipSelector);
      if (!element || element === hovered.current?.element) return;
      const reference = latest.current.references.find(item => item.version_id === element.dataset.promptReference);
      if (!reference) return;
      clearHover();
      hovered.current = { reference, element };
      latest.current.onReferenceHover?.(reference, element.getBoundingClientRect());
    }}
    onMouseOut={event => {
      if (hovered.current && !(event.relatedTarget instanceof Node && hovered.current.element.contains(event.relatedTarget))) clearHover();
    }}
  />;
});

export default PromptEditor;
