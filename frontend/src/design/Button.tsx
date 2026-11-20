import { forwardRef } from "react";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes } from "react";

/*
  Shared Button / IconButton (design-system phase 1, MIGRATION item 4). Styles: design/button.css.

  The components only choose class names. Everything else is passed to the native element
  unchanged: accessible name, `type`, event handlers, `disabled`, ARIA attributes and the ref.
  In particular no default `type` is added, so a button inside a form keeps submitting as before.
*/

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

export function buttonClassName(variant: ButtonVariant, size: ButtonSize = "md", className?: string) {
  return ["ui-button", `ui-button--${variant}`, size === "sm" && "ui-button--sm", className]
    .filter(Boolean)
    .join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant: ButtonVariant;
  size?: ButtonSize;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size = "md", className, ...props },
  ref,
) {
  return <button ref={ref} className={buttonClassName(variant, size, className)} {...props} />;
});

/** A link that looks like a button (navigation or download, never an in-page action). */
type ButtonLinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  variant: ButtonVariant;
  size?: ButtonSize;
};

export const ButtonLink = forwardRef<HTMLAnchorElement, ButtonLinkProps>(function ButtonLink(
  { variant, size = "md", className, ...props },
  ref,
) {
  return <a ref={ref} className={buttonClassName(variant, size, className)} {...props} />;
});

/** Icon-only button. An accessible name is required because there is no visible text. */
type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label"> & {
  "aria-label": string;
  active?: boolean;
};

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { active = false, className, ...props },
  ref,
) {
  return <button ref={ref} className={["ui-icon-button", active && "active", className].filter(Boolean).join(" ")} {...props} />;
});
