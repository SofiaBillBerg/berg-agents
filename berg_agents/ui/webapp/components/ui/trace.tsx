"use client";

import * as React from "react";
import { cn } from "cn";
import {
  Button as ButtonPrimitive,
  type ButtonProps} from "react-aria-components";
import { RiArrowRightSLine } from "@remixicon/react";

import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";

function Trace({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "flex w-full min-w-0 flex-col gap-2 *:has-[>[data-slot=trace-line]]:flex *:has-[>[data-slot=trace-line]]:w-fit *:has-[>[data-slot=trace-line]]:max-w-full *:has-[>[data-slot=trace-line]]:min-w-0 *:has-[>[data-slot=trace-line]]:rounded-md *:has-[>[data-slot=trace-line]]:text-left *:has-[>[data-slot=trace-line]]:outline-none *:has-[>[data-slot=trace-line]]:focus-visible:ring-3 *:has-[>[data-slot=trace-line]]:focus-visible:ring-ring/50",
        className,
      )}
      data-slot="trace"
      {...props}
    />
  );
}

function TraceLine({
  className,
  status,
  ...props
}: React.ComponentProps<"span"> & {
  status?: "running" | "error" | "pending";
}) {
  return (
    <span
      className={cn(
        "flex w-fit max-w-full min-w-0 items-center gap-2 text-sm text-muted-foreground transition-colors in-[a,button]:cursor-pointer in-[a:hover,button:hover]:text-foreground data-[status=error]:text-destructive data-[status=error]:in-[a:hover,button:hover]:text-destructive data-[status=pending]:opacity-60 data-[status=running]:*:data-[slot=trace-title]:shimmer",
        className,
      )}
      data-slot="trace-line"
      data-status={status}
      {...props}
    />
  );
}

function TraceIcon({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-4 shrink-0 items-center justify-center [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 [[data-slot=trace-title]~&]:-ml-1",
        className,
      )}
      data-slot="trace-icon"
      {...props}
    />
  );
}

function TraceTitle({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn("min-w-0 truncate motion-reduce:shimmer-none", className)}
      data-slot="trace-title"
      {...props}
    />
  );
}

function TraceDescription({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "shrink-0 text-muted-foreground/70 tabular-nums",
        className,
      )}
      data-slot="trace-description"
      {...props}
    />
  );
}

function TraceCollapsible({
  className,
  ...props
}: Omit<React.ComponentProps<typeof Collapsible>, "isExpanded" | "className"> &
  (
    | { isExpanded?: undefined }
    | {
        isExpanded: boolean;
        onExpandedChange: NonNullable<
          React.ComponentProps<typeof Collapsible>["onExpandedChange"]
        >;
      }
  ) & {
    className?: string;
  }) {
  return (
    <Collapsible
      className={cn("flex w-full min-w-0 flex-col", className)}
      data-slot="trace-collapsible"
      {...props}
    />
  );
}

function TraceCollapsibleTrigger({
  className,
  children,
  ...props
}: Omit<ButtonProps, "className" | "children" | "slot"> & {
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <ButtonPrimitive
      slot="trigger"
      {...props}
      className={cn(
        "group/trace-collapsible-trigger flex w-fit max-w-full min-w-0 cursor-pointer items-center gap-1 rounded-md text-left text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 has-[[data-status=error]]:text-destructive",
        className,
      )}
      data-slot="trace-collapsible-trigger"
    >
      {children}
      <TraceIcon className="transition-transform group-aria-expanded/trace-collapsible-trigger:rotate-90">
        <RiArrowRightSLine />
      </TraceIcon>
    </ButtonPrimitive>
  );
}

function TraceCollapsibleContent({
  className,
  children,
  ...props
}: Omit<
  React.ComponentProps<typeof CollapsibleContent>,
  "className" | "children"
> & {
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <CollapsibleContent
      className="h-(--disclosure-panel-height) min-w-0 overflow-clip transition-[height] duration-200"
      data-slot="trace-collapsible-content"
      {...props}
    >
      <div
        className={cn(
          "mt-2 mb-1 ml-[calc(--spacing(2)-1px)] min-w-0 border-l pr-1 pl-4 leading-relaxed wrap-break-word text-muted-foreground",
          className,
        )}
        data-slot="trace-collapsible-content-inner"
      >
        {children}
      </div>
    </CollapsibleContent>
  );
}

export {
  Trace,
  TraceLine,
  TraceIcon,
  TraceTitle,
  TraceDescription,
  TraceCollapsible,
  TraceCollapsibleTrigger,
  TraceCollapsibleContent};
