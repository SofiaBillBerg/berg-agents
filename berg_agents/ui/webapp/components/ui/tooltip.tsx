"use client";

import * as React from "react";
import { cn } from "cn";
import {
  Focusable,
  OverlayArrow,
  Tooltip as TooltipPrimitive,
  TooltipTrigger as TooltipTriggerPrimitive} from "react-aria-components";

function TooltipTrigger({
  delay = 0,
  children,
  ...props
}: React.ComponentProps<typeof TooltipTriggerPrimitive>) {
  const [trigger, tooltip] = React.Children.toArray(children);

  return (
    <TooltipTriggerPrimitive
      data-slot="tooltip-trigger"
      delay={delay}
      {...props}
    >
      <Focusable>
        {trigger as React.ComponentProps<typeof Focusable>["children"]}
      </Focusable>
      {tooltip}
    </TooltipTriggerPrimitive>
  );
}

function Tooltip({
  className,
  placement = "top",
  offset = 4,
  crossOffset = 0,
  children,
  ...props
}: Omit<
  React.ComponentProps<typeof TooltipPrimitive>,
  "children" | "className"
> & {
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <TooltipPrimitive
      className={cn(
        // Themed with the app's own tokens (the ones globals.css maps into
        // Tailwind): a bordered surface on the page background with normal
        // foreground text — the same overlay idiom bubble.tsx uses, so the
        // tooltip reads correctly in both light and dark themes. The
        // shadcn-default inverted fill (bg-foreground/text-background) does
        // not belong to this app's palette.
        "z-50 inline-flex w-fit max-w-xs origin-(--trigger-anchor-point) items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground shadow-md has-data-[slot=kbd]:pr-1.5 data-entering:animate-in data-entering:fade-in-0 data-entering:zoom-in-95 data-exiting:animate-out data-exiting:fade-out-0 data-exiting:zoom-out-95 data-[placement=bottom]:slide-in-from-top-2 data-[placement=left]:slide-in-from-right-2 data-[placement=right]:slide-in-from-left-2 data-[placement=top]:slide-in-from-bottom-2 **:data-[slot=kbd]:relative **:data-[slot=kbd]:isolate **:data-[slot=kbd]:z-50 **:data-[slot=kbd]:rounded-sm",
        className,
      )}
      crossOffset={crossOffset}
      data-slot="tooltip-content"
      offset={offset}
      placement={placement}
      {...props}
    >
      {children}
      <OverlayArrow
        // Matches the content surface: page background, no separate fill,
        // so the arrow is the same color as the bubble it points from.
        className="z-50 size-2.5 translate-y-[calc(-50%-2px)] rotate-45 rounded-[2px] bg-background fill-background"
        style={({ placement, defaultStyle }) => ({
          ...defaultStyle,
          rotate: "0deg",
          translate: "0 0",
          transform:
            placement === "bottom"
              ? "translate(-50%, calc(50% + 2px)) rotate(45deg)"
              : placement === "top"
                ? "translate(-50%, calc(-50% - 2px)) rotate(45deg)"
                : placement === "left"
                  ? "translate(calc(-50% - 2px), -50%) rotate(45deg)"
                  : "translate(calc(50% + 2px), -50%) rotate(45deg)"})}
      />
    </TooltipPrimitive>
  );
}

export { Tooltip, TooltipTrigger };
