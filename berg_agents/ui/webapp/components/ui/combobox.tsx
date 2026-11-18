"use client";

import * as React from "react";
import { cn } from "cn";
import {
  Button as ButtonPrimitive,
  Collection,
  ComboBox as ComboBoxPrimitive,
  ComboBoxStateContext,
  ComboBoxValue as ComboBoxValuePrimitive,
  composeRenderProps,
  Group,
  Header as HeaderPrimitive,
  Input as InputPrimitive,
  ListBoxItem as ListBoxItemPrimitive,
  ListBox as ListBoxPrimitive,
  ListBoxSection as ListBoxSectionPrimitive,
  Popover as PopoverPrimitive,
  Separator as SeparatorPrimitive,
  TagGroup as TagGroupPrimitive,
  TagList as TagListPrimitive,
  Tag as TagPrimitive,
  type ButtonProps,
  type ComboBoxValueProps,
  type GroupProps,
  type HeaderProps,
  type InputProps,
  type ListBoxItemProps,
  type ListBoxProps,
  type ListBoxSectionProps,
  type SeparatorProps,
  type TagListProps,
  type TagProps} from "react-aria-components";
import { RiArrowDownSLine, RiCloseLine, RiCheckLine } from "@remixicon/react";

import { Button } from "@/components/ui/button";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput} from "@/components/ui/input-group";

function ComboboxValue<T>({ ...props }: ComboBoxValueProps<T>) {
  return <ComboBoxValuePrimitive data-slot="combobox-value" {...props} />;
}

function ComboboxTrigger({
  className,
  children,
  ...props
}: Omit<ButtonProps, "children"> & {
  children?: React.ReactNode;
}) {
  return (
    <ButtonPrimitive
      className={cn("[&_svg:not([class*='size-'])]:size-4", className)}
      data-slot="combobox-trigger"
      {...props}
    >
      {children}
      <RiArrowDownSLine className="pointer-events-none size-4 text-muted-foreground" />
    </ButtonPrimitive>
  );
}

function ComboboxClear({
  className,
  ...props
}: React.ComponentProps<typeof InputGroupButton>) {
  const state = React.useContext(ComboBoxStateContext);
  if (state?.inputValue === "") {
    return null;
  }

  return (
    <InputGroupButton
      aria-label="Clear"
      className={cn(className)}
      data-slot="combobox-clear"
      size="icon-xs"
      slot={null}
      variant="ghost"
      onPress={() => {
        state?.setValue(null);
      }}
      {...props}
    >
      <RiCloseLine className="pointer-events-none" />
    </InputGroupButton>
  );
}

function ComboboxInput({
  className,
  children,
  disabled = false,
  showTrigger = true,
  showClear = false,
  ...props
}: React.ComponentProps<"input"> & {
  showTrigger?: boolean;
  showClear?: boolean;
}) {
  return (
    <InputGroup className={cn("w-auto", className)}>
      <InputGroupInput disabled={disabled} {...props} />
      <InputGroupAddon align="inline-end">
        {showTrigger && (
          <InputGroupButton
            className="group-has-data-[slot=combobox-clear]/input-group:hidden data-pressed:bg-transparent [&_svg:not([class*='size-'])]:size-4"
            data-slot="combobox-trigger"
            isDisabled={disabled}
            size="icon-xs"
            variant="ghost"
          >
            <RiArrowDownSLine className="pointer-events-none size-4 text-muted-foreground" />
          </InputGroupButton>
        )}
        {showClear && <ComboboxClear isDisabled={disabled} />}
      </InputGroupAddon>
      {children}
    </InputGroup>
  );
}

function ComboboxContent({
  className,
  placement = "bottom",
  offset = 6,
  crossOffset = 0,
  anchor,
  ...props
}: Omit<
  React.ComponentProps<typeof PopoverPrimitive>,
  "className" | "children"
> & {
  className?: string;
  children?: React.ReactNode;
  anchor?: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <PopoverPrimitive
      className={cn(
        "dark isolate z-50 max-h-72 w-(--trigger-width) min-w-36 origin-(--trigger-anchor-point) overflow-hidden rounded-lg text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 data-entering:animate-in data-entering:fade-in-0 data-entering:zoom-in-95 data-exiting:animate-out data-exiting:fade-out-0 data-exiting:zoom-out-95 data-[placement=bottom]:slide-in-from-top-2 data-[placement=left]:slide-in-from-right-2 data-[placement=right]:slide-in-from-left-2 data-[placement=top]:slide-in-from-bottom-2 **:data-[slot$=-item]:data-focused:bg-foreground/10 *:data-[slot=input-group]:m-1 *:data-[slot=input-group]:mb-0 *:data-[slot=input-group]:h-8 *:data-[slot=input-group]:border-input/30 *:data-[slot=input-group]:bg-input/30 *:data-[slot=input-group]:shadow-none animate-none! relative bg-popover/70 before:pointer-events-none before:absolute before:inset-0 before:-z-1 before:rounded-[inherit] before:backdrop-blur-2xl before:backdrop-saturate-150 **:data-[slot$=-item]:focus:bg-foreground/10 **:data-[slot$=-item]:data-highlighted:bg-foreground/10 **:data-[slot$=-separator]:bg-foreground/5 **:data-[slot$=-trigger]:focus:bg-foreground/10 **:data-[slot$=-trigger]:aria-expanded:bg-foreground/10! **:data-[variant=destructive]:focus:bg-foreground/10! **:data-[variant=destructive]:text-accent-foreground! **:data-[variant=destructive]:**:text-accent-foreground!",
        className,
      )}
      crossOffset={crossOffset}
      data-slot="combobox-content"
      offset={offset}
      placement={placement}
      triggerRef={anchor}
      {...props}
    />
  );
}

function ComboboxList<T extends object>({
  className,
  ...props
}: ListBoxProps<T>) {
  return (
    <ListBoxPrimitive
      className={cn(
        "group/combobox-content no-scrollbar max-h-[inherit] scroll-py-1 overflow-y-auto overscroll-contain p-1 data-empty:p-0",
        className,
      )}
      data-slot="combobox-list"
      {...props}
    />
  );
}

function ComboboxItem<T extends object>({
  className,
  children,
  ...props
}: ListBoxItemProps<T>) {
  return (
    <ListBoxItemPrimitive
      className={cn(
        "relative flex w-full cursor-default items-center gap-2 rounded-md py-1 pr-8 pl-1.5 text-sm outline-hidden select-none data-focused:bg-accent data-focused:text-accent-foreground not-data-[variant=destructive]:data-focused:**:text-accent-foreground data-highlighted:bg-accent data-highlighted:text-accent-foreground not-data-[variant=destructive]:data-highlighted:**:text-accent-foreground data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      data-slot="combobox-item"
      textValue={typeof children === "string" ? children : undefined}
      {...props}
    >
      {composeRenderProps(children, (children, { isSelected }) => (
        <>
          {children}
          <span className="pointer-events-none absolute right-2 flex size-4 items-center justify-center">
            {isSelected ? (
              <RiCheckLine className="pointer-events-none" />
            ) : null}
          </span>
        </>
      ))}
    </ListBoxItemPrimitive>
  );
}

function ComboboxGroup<T extends object>({
  className,
  ...props
}: ListBoxSectionProps<T>) {
  return (
    <ListBoxSectionPrimitive
      className={cn(className)}
      data-slot="combobox-group"
      {...props}
    />
  );
}

function ComboboxLabel({ className, ...props }: HeaderProps) {
  return (
    <HeaderPrimitive
      className={cn("px-2 py-1.5 text-xs text-muted-foreground", className)}
      data-slot="combobox-label"
      {...props}
    />
  );
}

function ComboboxEmpty({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "hidden w-full justify-center py-2 text-center text-sm text-muted-foreground group-data-empty/combobox-content:flex",
        className,
      )}
      data-slot="combobox-empty"
      {...props}
    />
  );
}

function ComboboxSeparator({ className, ...props }: SeparatorProps) {
  return (
    <SeparatorPrimitive
      className={cn("-mx-1 my-1 h-px bg-border", className)}
      data-slot="combobox-separator"
      {...props}
    />
  );
}

function ComboboxChips({ children, className, ...props }: GroupProps) {
  return (
    <Group
      className={cn(
        "flex min-h-8 flex-wrap items-center gap-1 rounded-lg border border-input bg-transparent bg-clip-padding px-2.5 py-1 text-sm transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 has-aria-invalid:border-destructive has-aria-invalid:ring-3 has-aria-invalid:ring-destructive/20 has-data-[slot=combobox-chip]:px-1 dark:bg-input/30 dark:has-aria-invalid:border-destructive/50 dark:has-aria-invalid:ring-destructive/40",
        className,
      )}
      data-slot="combobox-chips"
      {...props}
    >
      {children}
    </Group>
  );
}

function ComboboxChipList<T extends object>({
  className,
  ...props
}: Omit<TagListProps<T>, "className" | "items"> & {
  className?: string;
}) {
  return (
    <ComboBoxValuePrimitive<T> className="contents">
      {({ selectedItems, state }) => (
        <TagGroupPrimitive
          className={cn("contents", className)}
          data-slot="combobox-chip-list"
          onRemove={(keys) => {
            if (Array.isArray(state.value)) {
              state.setValue(state.value.filter((k) => !keys.has(k)));
            }
          }}
        >
          <TagListPrimitive
            className="contents"
            items={selectedItems.filter((item) => item != null)}
            {...props}
          />
        </TagGroupPrimitive>
      )}
    </ComboBoxValuePrimitive>
  );
}

function ComboboxChip({
  className,
  children,
  showRemove = true,
  ...props
}: Omit<TagProps, "children"> & {
  showRemove?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <TagPrimitive
      className={cn(
        "flex h-[calc(--spacing(5.25))] w-fit items-center justify-center gap-1 rounded-sm bg-muted px-1.5 text-xs font-medium whitespace-nowrap text-foreground has-disabled:pointer-events-none has-disabled:cursor-not-allowed has-disabled:opacity-50 has-data-[slot=combobox-chip-remove]:pr-0",
        className,
      )}
      data-slot="combobox-chip"
      {...props}
    >
      {children}
      {showRemove && (
        <Button
          className="-ml-1 opacity-50 hover:opacity-100"
          data-slot="combobox-chip-remove"
          size="icon-xs"
          slot="remove"
          variant="ghost"
        >
          <RiCloseLine className="pointer-events-none" />
        </Button>
      )}
    </TagPrimitive>
  );
}

function ComboboxChipsInput({ className, ...props }: InputProps) {
  const state = React.useContext(ComboBoxStateContext);
  return (
    <InputPrimitive
      className={cn("min-w-16 flex-1 outline-none", className)}
      data-slot="combobox-chip-input"
      onKeyDown={(e) => {
        if (
          e.key === "Backspace" &&
          e.currentTarget.value === "" &&
          Array.isArray(state?.value) &&
          state.value.length > 0
        ) {
          e.preventDefault();
          state.setValue(state.value.slice(0, -1));
        }
      }}
      {...props}
    />
  );
}

function useComboboxAnchor() {
  return React.useRef<HTMLDivElement | null>(null);
}

export {
  ComboBoxPrimitive as Combobox,
  ComboboxInput,
  ComboboxContent,
  ComboboxList,
  ComboboxItem,
  ComboboxGroup,
  ComboboxLabel,
  Collection as ComboboxCollection,
  ComboboxEmpty,
  ComboboxSeparator,
  ComboboxChips,
  ComboboxChip,
  ComboboxChipList,
  ComboboxChipsInput,
  ComboboxTrigger,
  ComboboxValue,
  useComboboxAnchor};
