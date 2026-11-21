"use client";

import * as React from "react";
import { cn } from "cn";
import {
  DisclosurePanel as AccordionContentPrimitive,
  Heading as AccordionHeaderPrimitive,
  Disclosure as AccordionItemPrimitive,
  DisclosureGroup as AccordionPrimitive,
  Button as AccordionTriggerPrimitive,
  type ButtonProps,
  type DisclosureGroupProps,
  type DisclosurePanelProps,
  type DisclosureProps} from "react-aria-components";
import { RiArrowDownSLine, RiArrowUpSLine } from "@remixicon/react";

function Accordion({ className, ...props }: DisclosureGroupProps) {
  return (
    <AccordionPrimitive
      className={cn("flex w-full flex-col", className)}
      data-slot="accordion"
      {...props}
    />
  );
}

function AccordionItem({ className, ...props }: DisclosureProps) {
  return (
    <AccordionItemPrimitive
      className={cn("not-last:border-b", className)}
      data-slot="accordion-item"
      {...props}
    />
  );
}

function AccordionTrigger({
  className,
  children,
  ...props
}: Omit<ButtonProps, "children"> & { children: React.ReactNode }) {
  return (
    <AccordionHeaderPrimitive className="flex">
      <AccordionTriggerPrimitive
        className={cn(
          "group/accordion-trigger relative flex flex-1 items-start justify-between rounded-lg border border-transparent py-2.5 text-left text-sm font-medium transition-all outline-none hover:underline focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:after:border-ring disabled:pointer-events-none disabled:opacity-50 **:data-[slot=accordion-trigger-icon]:ml-auto **:data-[slot=accordion-trigger-icon]:size-4 **:data-[slot=accordion-trigger-icon]:text-muted-foreground",
          className,
        )}
        data-slot="accordion-trigger"
        slot="trigger"
        {...props}
      >
        {children}
        <RiArrowDownSLine
          className="pointer-events-none shrink-0 group-aria-expanded/accordion-trigger:hidden"
          data-slot="accordion-trigger-icon"
        />
        <RiArrowUpSLine
          className="pointer-events-none hidden shrink-0 group-aria-expanded/accordion-trigger:inline"
          data-slot="accordion-trigger-icon"
        />
      </AccordionTriggerPrimitive>
    </AccordionHeaderPrimitive>
  );
}

function AccordionContent({
  className,
  children,
  ...props
}: DisclosurePanelProps) {
  return (
    <AccordionContentPrimitive
      className="h-(--disclosure-panel-height) overflow-clip text-sm transition-[height] data-open:animate-accordion-down data-closed:animate-accordion-up"
      data-slot="accordion-content"
      {...props}
    >
      <div
        className={cn(
          "pt-0 pb-2.5 [&_a]:underline [&_a]:underline-offset-3 [&_a]:hover:text-foreground [&_p:not(:last-child)]:mb-4",
          className,
        )}
      >
        {children}
      </div>
    </AccordionContentPrimitive>
  );
}

export { Accordion, AccordionItem, AccordionTrigger, AccordionContent };
