"use client";

// shadcnblocks-authored React Aria wrapper — NOT downloaded from ui.shadcn.com.
// shadcn's React Aria registry has no menubar; this mirrors the Radix menubar API on top of react-aria-components Menu/MenuTrigger.
// Served to aria-nova projects as @shadcnblocks/ui-extras/menubar. If shadcn ships an
// official `menubar` for the aria style, delete this file and use theirs.

import * as React from "react";
import {
  Button as ButtonPrimitive,
  composeRenderProps,
  Header as HeaderPrimitive,
  MenuItem as MenuItemPrimitive,
  Menu as MenuPrimitive,
  MenuSection as MenuSectionPrimitive,
  MenuTrigger as MenuTriggerPrimitive,
  Popover as PopoverPrimitive,
  Separator as SeparatorPrimitive,
  SubmenuTrigger as SubmenuTriggerPrimitive,
  Toolbar as ToolbarPrimitive,
  type MenuItemProps as MenuItemPrimitiveProps,
  type MenuSectionProps as MenuSectionPrimitiveProps,
  type Selection} from "react-aria-components";
import { CheckIcon, ChevronRightIcon } from "lucide-react";
import { cn } from "cn";

function Menubar({
  className,
  value: _value,
  defaultValue: _defaultValue,
  onValueChange: _onValueChange,
  ...props
}: React.ComponentProps<typeof ToolbarPrimitive> & {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
}) {
  return (
    <ToolbarPrimitive
      aria-label="Menubar"
      className={cn(
        "flex h-8 items-center gap-0.5 rounded-lg border p-[3px]",
        className,
      )}
      data-slot="menubar"
      {...props}
    />
  );
}

function MenubarMenu({
  open,
  isOpen,
  ...props
}: React.ComponentProps<typeof MenuTriggerPrimitive> & {
  open?: boolean;
}) {
  return (
    <MenuTriggerPrimitive
      data-slot="menubar-menu"
      isOpen={isOpen ?? open}
      {...props}
    />
  );
}

function MenubarGroup({
  ...props
}: Omit<MenuSectionPrimitiveProps<object>, "children"> & {
  children?: React.ReactNode;
}) {
  return <MenuSectionPrimitive data-slot="menubar-group" {...props} />;
}

function MenubarPortal({ children }: { children?: React.ReactNode }) {
  return <>{children}</>;
}

function MenubarTrigger({
  className,
  ...props
}: React.ComponentProps<typeof ButtonPrimitive>) {
  return (
    <ButtonPrimitive
      className={cn(
        "flex items-center rounded-sm px-1.5 py-[2px] text-sm font-medium outline-hidden select-none hover:bg-muted aria-expanded:bg-muted",
        className,
      )}
      data-slot="menubar-trigger"
      {...props}
    />
  );
}

function MenubarContent({
  "data-slot": dataSlot = "menubar-content",
  className,
  align = "start",
  alignOffset = -4,
  sideOffset = 8,
  side = "bottom",
  placement,
  offset,
  crossOffset,
  children,
  ...props
}: Omit<
  React.ComponentProps<typeof MenuPrimitive<object>>,
  "children" | "className"
> &
  Pick<
    React.ComponentProps<typeof PopoverPrimitive>,
    "placement" | "offset" | "crossOffset"
  > & {
    "data-slot"?: string;
    className?: string;
    children?: React.ReactNode;
    align?: "start" | "center" | "end";
    alignOffset?: number;
    sideOffset?: number;
    side?: "top" | "bottom" | "left" | "right";
  }) {
  const resolvedPlacement =
    placement ??
    (`${side}${align === "center" ? "" : ` ${align}`}` as React.ComponentProps<
      typeof PopoverPrimitive
    >["placement"]);

  return (
    <PopoverPrimitive
      className={cn(
        "z-50 min-w-36 origin-(--trigger-anchor-point) overflow-hidden rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 outline-none data-[placement=bottom]:slide-in-from-top-2 data-[placement=left]:slide-in-from-right-2 data-[placement=right]:slide-in-from-left-2 data-[placement=top]:slide-in-from-bottom-2 data-entering:animate-in data-entering:fade-in-0 data-entering:zoom-in-95 **:data-[slot$=-item]:data-focused:bg-accent",
        className,
      )}
      crossOffset={crossOffset ?? alignOffset}
      data-slot={dataSlot}
      offset={offset ?? sideOffset}
      placement={resolvedPlacement}
    >
      <MenuPrimitive
        className="max-h-[inherit] overflow-x-hidden overflow-y-auto outline-hidden"
        {...props}
      >
        {children}
      </MenuPrimitive>
    </PopoverPrimitive>
  );
}

function MenubarItem({
  className,
  inset,
  variant = "default",
  disabled,
  isDisabled,
  children,
  onSelect,
  onAction,
  ...props
}: MenuItemPrimitiveProps<object> & {
  inset?: boolean;
  variant?: "default" | "destructive";
  disabled?: boolean;
  onSelect?: () => void;
}) {
  return (
    <MenuItemPrimitive
      className={cn(
        "group/menubar-item relative flex cursor-default items-center gap-1.5 rounded-md px-1.5 py-1 text-sm outline-hidden select-none focus:bg-accent focus:text-accent-foreground not-data-[variant=destructive]:focus:**:text-accent-foreground data-inset:pl-7 data-[variant=destructive]:text-destructive data-[variant=destructive]:focus:bg-destructive/10 data-[variant=destructive]:focus:text-destructive dark:data-[variant=destructive]:focus:bg-destructive/20 data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 data-[variant=destructive]:*:[svg]:text-destructive!",
        className,
      )}
      data-inset={inset}
      data-slot="menubar-item"
      data-variant={variant}
      isDisabled={isDisabled ?? disabled}
      textValue={typeof children === "string" ? children : props.textValue}
      onAction={onAction ?? onSelect}
      {...props}
    >
      {children}
    </MenuItemPrimitive>
  );
}

function MenubarCheckboxItem({
  className,
  children,
  checked,
  inset,
  disabled,
  isDisabled,
  onCheckedChange,
  ...props
}: MenuItemPrimitiveProps<object> & {
  inset?: boolean;
  checked?: boolean;
  disabled?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}) {
  const id = React.useId();
  const [uncontrolled, setUncontrolled] = React.useState(!!checked);
  const isControlled = checked !== undefined;
  const isChecked = isControlled ? checked : uncontrolled;

  return (
    <MenuSectionPrimitive
      selectedKeys={isChecked ? new Set([id]) : new Set()}
      selectionMode="multiple"
      onSelectionChange={(keys: Selection) => {
        const next = keys !== "all" && keys.has(id);
        onCheckedChange?.(next);
        if (!isControlled) {
          setUncontrolled(next);
        }
      }}
    >
      <MenuItemPrimitive
        className={cn(
          "relative flex cursor-default items-center gap-1.5 rounded-md py-1 pr-1.5 pl-7 text-sm outline-hidden select-none focus:bg-accent focus:text-accent-foreground focus:**:text-accent-foreground data-inset:pl-7 data-disabled:pointer-events-none [&_svg]:pointer-events-none [&_svg]:shrink-0",
          className,
        )}
        data-inset={inset}
        data-slot="menubar-checkbox-item"
        id={id}
        isDisabled={isDisabled ?? disabled}
        textValue={typeof children === "string" ? children : props.textValue}
        {...props}
      >
        {composeRenderProps(children, (children, { isSelected }) => (
          <>
            <span className="pointer-events-none absolute left-1.5 flex size-4 items-center justify-center [&_svg:not([class*='size-'])]:size-4">
              {isSelected ? <CheckIcon /> : null}
            </span>
            {children}
          </>
        ))}
      </MenuItemPrimitive>
    </MenuSectionPrimitive>
  );
}

function MenubarRadioGroup({
  value,
  onValueChange,
  children,
  ...props
}: Omit<
  MenuSectionPrimitiveProps<object>,
  "children" | "selectedKeys" | "onSelectionChange" | "selectionMode"
> & {
  children?: React.ReactNode;
  value?: string;
  onValueChange?: (value: string) => void;
}) {
  return (
    <MenuSectionPrimitive
      data-slot="menubar-radio-group"
      selectedKeys={value != null ? new Set([value]) : undefined}
      selectionMode="single"
      onSelectionChange={(keys: Selection) => {
        if (keys === "all") {
          return;
        }
        const next = keys.values().next().value;
        if (next != null) {
          onValueChange?.(String(next));
        }
      }}
      {...props}
    >
      {children}
    </MenuSectionPrimitive>
  );
}

function MenubarRadioItem({
  className,
  children,
  inset,
  value,
  disabled,
  isDisabled,
  ...props
}: MenuItemPrimitiveProps<object> & {
  inset?: boolean;
  value?: string;
  disabled?: boolean;
}) {
  return (
    <MenuItemPrimitive
      className={cn(
        "relative flex cursor-default items-center gap-1.5 rounded-md py-1 pr-1.5 pl-7 text-sm outline-hidden select-none focus:bg-accent focus:text-accent-foreground focus:**:text-accent-foreground data-inset:pl-7 data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      data-inset={inset}
      data-slot="menubar-radio-item"
      id={value}
      isDisabled={isDisabled ?? disabled}
      textValue={typeof children === "string" ? children : props.textValue}
      {...props}
    >
      {composeRenderProps(children, (children, { isSelected }) => (
        <>
          <span className="pointer-events-none absolute left-1.5 flex size-4 items-center justify-center [&_svg:not([class*='size-'])]:size-4">
            {isSelected ? <CheckIcon /> : null}
          </span>
          {children}
        </>
      ))}
    </MenuItemPrimitive>
  );
}

function MenubarLabel({
  className,
  inset,
  ...props
}: React.ComponentProps<typeof HeaderPrimitive> & {
  inset?: boolean;
}) {
  return (
    <HeaderPrimitive
      className={cn(
        "px-1.5 py-1 text-sm font-medium data-inset:pl-7",
        className,
      )}
      data-inset={inset}
      data-slot="menubar-label"
      {...props}
    />
  );
}

function MenubarSeparator({
  className,
  ...props
}: React.ComponentProps<typeof SeparatorPrimitive>) {
  return (
    <SeparatorPrimitive
      className={cn("-mx-1 my-1 h-px bg-border", className)}
      data-slot="menubar-separator"
      {...props}
    />
  );
}

function MenubarShortcut({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "ml-auto text-xs tracking-widest text-muted-foreground group-focus/menubar-item:text-accent-foreground",
        className,
      )}
      data-slot="menubar-shortcut"
      {...props}
    />
  );
}

function MenubarSub({
  ...props
}: React.ComponentProps<typeof SubmenuTriggerPrimitive>) {
  return <SubmenuTriggerPrimitive data-slot="menubar-sub" {...props} />;
}

function MenubarSubTrigger({
  className,
  inset,
  children,
  ...props
}: MenuItemPrimitiveProps<object> & {
  inset?: boolean;
}) {
  return (
    <MenuItemPrimitive
      className={cn(
        "flex cursor-default items-center gap-1.5 rounded-md px-1.5 py-1 text-sm outline-none select-none focus:bg-accent focus:text-accent-foreground data-inset:pl-7 data-open:bg-accent data-open:text-accent-foreground [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      data-inset={inset}
      data-slot="menubar-sub-trigger"
      textValue={typeof children === "string" ? children : props.textValue}
      {...props}
    >
      {composeRenderProps(children, (children) => (
        <>
          {children}
          <ChevronRightIcon className="ml-auto size-4" />
        </>
      ))}
    </MenuItemPrimitive>
  );
}

function MenubarSubContent({
  className,
  placement = "end top",
  crossOffset = -3,
  offset = 0,
  ...props
}: React.ComponentProps<typeof MenubarContent>) {
  return (
    <MenubarContent
      className={cn(
        "z-50 min-w-32 origin-(--trigger-anchor-point) overflow-hidden rounded-lg bg-popover p-1 text-popover-foreground shadow-lg ring-1 ring-foreground/10 duration-100 outline-none data-[placement=bottom]:slide-in-from-top-2 data-[placement=left]:slide-in-from-right-2 data-[placement=right]:slide-in-from-left-2 data-[placement=top]:slide-in-from-bottom-2 data-entering:animate-in data-entering:fade-in-0 data-entering:zoom-in-95 data-exiting:animate-out data-exiting:fade-out-0 data-exiting:zoom-out-95",
        className,
      )}
      crossOffset={crossOffset}
      data-slot="menubar-sub-content"
      offset={offset}
      placement={placement}
      {...props}
    />
  );
}

export {
  Menubar,
  MenubarPortal,
  MenubarMenu,
  MenubarTrigger,
  MenubarContent,
  MenubarGroup,
  MenubarSeparator,
  MenubarLabel,
  MenubarItem,
  MenubarShortcut,
  MenubarCheckboxItem,
  MenubarRadioGroup,
  MenubarRadioItem,
  MenubarSub,
  MenubarSubTrigger,
  MenubarSubContent};
