"use client";

import * as React from "react";
import { cn } from "cn";
import {
  Dialog as DialogPrimitive,
  DialogTrigger as DialogTriggerPrimitive,
  Heading,
  ModalOverlay as ModalOverlayPrimitive,
  Modal as ModalPrimitive,
  type DialogProps as DialogPrimitiveProps,
  type DialogTriggerProps as DialogTriggerPrimitiveProps,
  type ModalOverlayProps as ModalOverlayPrimitiveProps} from "react-aria-components";
import { RiCloseLine } from "@remixicon/react";

import { Button } from "@/components/ui/button";

function DialogTrigger({ ...props }: DialogTriggerPrimitiveProps) {
  return <DialogTriggerPrimitive data-slot="dialog-trigger" {...props} />;
}

function DialogClose({
  className,
  variant = "outline",
  size = "default",
  ...props
}: React.ComponentProps<typeof Button>) {
  return (
    <Button
      className={cn(className)}
      data-slot="dialog-close"
      size={size}
      slot="close"
      variant={variant}
      {...props}
    />
  );
}

function DialogOverlay({
  className,
  children,
  ...props
}: Omit<ModalOverlayPrimitiveProps, "className" | "children"> & {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <ModalOverlayPrimitive
      className={cn(
        "fixed inset-0 isolate z-50 bg-black/10 duration-100 data-entering:animate-in data-entering:fade-in-0 data-exiting:animate-out data-exiting:fade-out-0 supports-backdrop-filter:backdrop-blur-xs",
        className,
      )}
      data-slot="dialog-overlay"
      {...props}
    >
      {children}
    </ModalOverlayPrimitive>
  );
}

function Dialog({
  className,
  children,
  showCloseButton = true,
  isDismissable = true,
  ...props
}: Omit<ModalOverlayPrimitiveProps, "className" | "children"> &
  Pick<React.ComponentProps<typeof ModalPrimitive>, "isDismissable"> & {
    className?: string;
    children: React.ReactNode;
    showCloseButton?: boolean;
  }) {
  return (
    <DialogOverlay isDismissable={isDismissable} {...props}>
      <ModalPrimitive
        className={cn(
          "fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl bg-popover p-4 text-sm text-popover-foreground ring-1 ring-foreground/10 duration-100 outline-none data-entering:animate-in data-entering:fade-in-0 data-entering:zoom-in-95 data-exiting:animate-out data-exiting:fade-out-0 data-exiting:zoom-out-95 sm:max-w-sm",
          className,
        )}
        data-slot="dialog-content"
      >
        <DialogPrimitive
          className="[display:inherit] [gap:inherit] outline-none"
          data-slot="dialog"
        >
          {children}
          {showCloseButton && (
            <DialogClose
              className="absolute top-2 right-2"
              size="icon-sm"
              variant="ghost"
            >
              <RiCloseLine />
              <span className="sr-only">Close</span>
            </DialogClose>
          )}
        </DialogPrimitive>
      </ModalPrimitive>
    </DialogOverlay>
  );
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("flex flex-col gap-2", className)}
      data-slot="dialog-header"
      {...props}
    />
  );
}

function DialogFooter({
  className,
  showCloseButton = false,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  showCloseButton?: boolean;
}) {
  return (
    <div
      className={cn(
        "-mx-4 -mb-4 flex flex-col-reverse gap-2 rounded-b-xl border-t bg-muted/50 p-4 sm:flex-row sm:justify-end",
        className,
      )}
      data-slot="dialog-footer"
      {...props}
    >
      {children}
      {showCloseButton && <DialogClose variant="outline">Close</DialogClose>}
    </div>
  );
}

function DialogTitle({
  className,
  ...props
}: Omit<React.ComponentProps<typeof Heading>, "slot">) {
  return (
    <Heading
      className={cn(
        "font-heading text-base leading-none font-medium",
        className,
      )}
      data-slot="dialog-title"
      slot="title"
      {...props}
    />
  );
}

function DialogDescription({
  className,
  ...props
}: Omit<React.ComponentProps<"div">, "slot">) {
  return (
    <div
      className={cn(
        "text-sm text-muted-foreground *:[a]:underline *:[a]:underline-offset-3 *:[a]:hover:text-foreground",
        className,
      )}
      data-slot="dialog-description"
      {...props}
    />
  );
}

export {
  type DialogPrimitiveProps,
  type DialogTriggerPrimitiveProps,
  Dialog,
  DialogClose,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogTitle,
  DialogTrigger};
