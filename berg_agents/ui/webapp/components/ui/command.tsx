"use client";

import * as React from "react";
import { cn } from "cn";
import {
  Autocomplete,
  Collection,
  composeRenderProps,
  Header,
  Input,
  Menu,
  MenuItem,
  MenuSection,
  SearchField,
  Separator,
  useFilter,
  type AutocompleteProps,
  type InputProps,
  type MenuItemProps,
  type MenuProps,
  type MenuSectionProps,
  type SeparatorProps} from "react-aria-components";
import { RiSearchLine, RiCheckLine } from "@remixicon/react";

import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogTitle} from "@/components/ui/dialog";
import { InputGroup, InputGroupAddon } from "@/components/ui/input-group";

function Command({
  className,
  dir,
  style,
  ...props
}: Omit<AutocompleteProps, "className" | "style"> & {
  className?: string;
  dir?: React.HTMLAttributes<HTMLDivElement>["dir"];
  style?: React.CSSProperties;
}) {
  const { contains } = useFilter({ sensitivity: "base" });
  return (
    <div
      className={cn(
        "flex size-full flex-col overflow-hidden rounded-xl! bg-popover p-1 text-popover-foreground",
        className,
      )}
      data-slot="command"
      dir={dir}
      style={style}
    >
      <Autocomplete {...props} filter={props.filter || contains}>
        {props.children}
      </Autocomplete>
    </div>
  );
}

function CommandDialog({
  title = "Command Palette",
  description = "Search for a command to run...",
  children,
  open,
  onOpenChange,
  className,
  showCloseButton = false,
  ...props
}: Omit<
  React.ComponentProps<typeof Dialog>,
  "children" | "className" | "isOpen" | "onOpenChange"
> & {
  title?: string;
  description?: string;
  open?: boolean;
  onOpenChange?: (isOpen: boolean) => void;
  className?: string;
  showCloseButton?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Dialog
      isDismissable
      className={cn(
        "top-1/3 translate-y-0 overflow-hidden rounded-xl! p-0",
        className,
      )}
      isOpen={open}
      showCloseButton={showCloseButton}
      onOpenChange={onOpenChange}
      {...props}
    >
      <DialogHeader className="sr-only">
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>
      {children}
    </Dialog>
  );
}

function CommandInput({ className, ...props }: InputProps) {
  return (
    <SearchField
      autoFocus
      aria-label={props.placeholder || "Search"}
      className="p-1 pb-0"
      data-slot="command-input-wrapper"
    >
      <InputGroup className="h-8! rounded-lg! border-input/30 bg-input/30 shadow-none! *:data-[slot=input-group-addon]:pl-2!">
        <Input
          {...props}
          className={cn(
            "w-full text-sm outline-hidden disabled:cursor-not-allowed disabled:opacity-50 [&::-webkit-search-cancel-button]:hidden",
            className,
          )}
          data-slot="command-input"
        />
        <InputGroupAddon>
          <RiSearchLine className="size-4 shrink-0 opacity-50" />
        </InputGroupAddon>
      </InputGroup>
    </SearchField>
  );
}

function CommandList<T extends object>({ className, ...props }: MenuProps<T>) {
  return (
    <Menu
      {...props}
      className={cn(
        "no-scrollbar max-h-72 scroll-py-1 overflow-x-hidden overflow-y-auto outline-none",
        className,
      )}
      data-slot="command-list"
    />
  );
}

function CommandEmpty({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("py-6 text-center text-sm", className)}
      data-slot="command-empty"
      {...props}
    />
  );
}

function CommandGroup<T extends object>({
  className,
  children,
  items,
  heading,
  ...props
}: MenuSectionProps<T> & { heading?: string }) {
  return (
    <MenuSection
      className={cn(
        "overflow-hidden p-1 text-foreground **:[[cmdk-group-heading]]:px-2 **:[[cmdk-group-heading]]:py-1.5 **:[[cmdk-group-heading]]:text-xs **:[[cmdk-group-heading]]:font-medium **:[[cmdk-group-heading]]:text-muted-foreground",
        className,
      )}
      data-slot="command-group"
      {...props}
    >
      {heading && <Header cmdk-group-heading="">{heading}</Header>}
      <Collection items={items}>{children}</Collection>
    </MenuSection>
  );
}

function CommandSeparator({ className, ...props }: SeparatorProps) {
  return (
    <Separator
      className={cn("-mx-1 h-px bg-border", className)}
      data-slot="command-separator"
      {...props}
    />
  );
}

function CommandItem<T extends object>({
  className,
  children,
  textValue,
  ...props
}: MenuItemProps<T>) {
  return (
    <MenuItem
      {...props}
      className={cn(
        "group/command-item relative flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden select-none in-data-[slot=dialog-content]:rounded-lg! data-focused:bg-muted data-focused:text-foreground data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50 data-selected:bg-muted data-selected:text-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 data-focused:*:[svg]:text-foreground data-selected:*:[svg]:text-foreground",
        className,
      )}
      data-slot="command-item"
      textValue={
        textValue || (typeof children === "string" ? children : undefined)
      }
    >
      {composeRenderProps(children, (children) => (
        <>
          {children}
          <RiCheckLine className="ml-auto opacity-0 group-has-data-[slot=command-shortcut]/command-item:hidden group-data-[checked=true]/command-item:opacity-100" />
        </>
      ))}
    </MenuItem>
  );
}

function CommandShortcut({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "ml-auto text-xs tracking-widest text-muted-foreground group-data-focused/command-item:text-foreground group-data-selected/command-item:text-foreground",
        className,
      )}
      data-slot="command-shortcut"
      {...props}
    />
  );
}

export {
  Command,
  CommandDialog,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandShortcut,
  CommandSeparator};
