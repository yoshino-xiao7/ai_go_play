/**
 * Copy text and report whether it really reached the clipboard. The async Clipboard API needs a
 * focused secure document; when it is refused (permissions, an embedded webview, focus lost to a
 * dialog) the selection-based copy still works from inside the user's click.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall through to the selection copy */ }
  const active = document.activeElement as HTMLElement | null;
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
  document.body.appendChild(field);
  field.select();
  let done = false;
  try { done = document.execCommand("copy"); } catch { done = false; }
  field.remove();
  active?.focus({ preventScroll: true });
  return done;
}
