"use client";

// shadcnblocks-authored React Aria wrapper — NOT downloaded from ui.shadcn.com.
// shadcn's React Aria registry has no navigation-menu; this mirrors the Radix navigation-menu API (NavigationMenu, NavigationMenuList, NavigationMenuItem, NavigationMenuTrigger, NavigationMenuContent, NavigationMenuLink, NavigationMenuViewport, navigationMenuTriggerStyle) on top of react-aria-components.
// Served to aria-nova projects as @shadcnblocks/ui-extras/navigation-menu. If shadcn ships an
// official `navigation-menu` for the aria style, delete this file and use theirs.

import * as React from "react";
import { createPortal } from "react-dom";
import { cva } from "class-variance-authority";
import {
  Button as ButtonPrimitive,
  Link as LinkPrimitive} from "react-aria-components";
import { ChevronDownIcon } from "lucide-react";
import { cn } from "cn";

const ANIMATION_MS = 180;

type NavigationMenuContextValue = {
  viewport: boolean;
  viewportEl: HTMLDivElement | null;
  setViewportEl: (node: HTMLDivElement | null) => void;
  openItemId: string | null;
  setOpenItemId: (id: string | null) => void;
  visibleItemId: string | null;
};

const NavigationMenuContext =
  React.createContext<NavigationMenuContextValue | null>(null);

type NavigationMenuItemContextValue = {
  id: string;
  open: boolean;
  setOpen: (open: boolean) => void;
};

const NavigationMenuItemContext =
  React.createContext<NavigationMenuItemContextValue | null>(null);

function NavigationMenu({
  className,
  children,
  viewport = true,
  delayDuration: _delayDuration,
  skipDelayDuration: _skipDelayDuration,
  ...props
}: React.ComponentProps<"nav"> & {
  viewport?: boolean;
  delayDuration?: number;
  skipDelayDuration?: number;
}) {
  const [openItemId, setOpenItemId] = React.useState<string | null>(null);
  const [visibleItemId, setVisibleItemId] = React.useState<string | null>(null);
  const [viewportEl, setViewportEl] = React.useState<HTMLDivElement | null>(
    null,
  );

  React.useEffect(() => {
    if (openItemId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setVisibleItemId(openItemId);
      return;
    }
    if (!visibleItemId) {
      return;
    }
    const timeout = window.setTimeout(() => {
      setVisibleItemId(null);
    }, ANIMATION_MS);
    return () => window.clearTimeout(timeout);
  }, [openItemId, visibleItemId]);

  React.useEffect(() => {
    if (!openItemId) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpenItemId(null);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [openItemId]);

  return (
    <NavigationMenuContext.Provider
      value={{
        viewport,
        viewportEl,
        setViewportEl,
        openItemId,
        setOpenItemId,
        visibleItemId}}
    >
      <nav
        className={cn(
          "group/navigation-menu relative flex max-w-max flex-1 items-center justify-center",
          className,
        )}
        data-slot="navigation-menu"
        data-viewport={viewport}
        onBlur={(event) => {
          if (
            !event.currentTarget.contains(event.relatedTarget as Node | null)
          ) {
            setOpenItemId(null);
          }
        }}
        onPointerLeave={() => {
          if (viewport) {
            setOpenItemId(null);
          }
        }}
        {...props}
      >
        {children}
        {viewport && <NavigationMenuViewport />}
      </nav>
    </NavigationMenuContext.Provider>
  );
}

function NavigationMenuList({
  className,
  ...props
}: React.ComponentProps<"ul">) {
  return (
    <ul
      className={cn(
        "group flex flex-1 list-none items-center justify-center gap-0",
        className,
      )}
      data-slot="navigation-menu-list"
      {...props}
    />
  );
}

function NavigationMenuItem({
  className,
  ...props
}: React.ComponentProps<"li">) {
  const id = React.useId();
  const root = React.useContext(NavigationMenuContext);
  const open = root?.openItemId === id;
  const setOpen = React.useCallback(
    (next: boolean) => {
      root?.setOpenItemId(
        next ? id : root.openItemId === id ? null : root.openItemId,
      );
    },
    [id, root],
  );

  return (
    <NavigationMenuItemContext.Provider value={{ id, open, setOpen }}>
      <li
        className={cn("relative", className)}
        data-open={open || undefined}
        data-slot="navigation-menu-item"
        onPointerEnter={() => {
          setOpen(true);
        }}
        onPointerLeave={() => {
          if (!root?.viewport) {
            setOpen(false);
          }
        }}
        {...props}
      />
    </NavigationMenuItemContext.Provider>
  );
}

const navigationMenuTriggerStyle = cva(
  "group/navigation-menu-trigger inline-flex h-9 w-max items-center justify-center rounded-lg px-2.5 py-1.5 text-sm font-medium transition-all outline-none hover:bg-muted focus:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-1 disabled:pointer-events-none disabled:opacity-50 data-popup-open:bg-muted/50 data-popup-open:hover:bg-muted data-open:bg-muted/50 data-open:hover:bg-muted data-open:focus:bg-muted",
);

function NavigationMenuTrigger({
  className,
  children,
  ...props
}: Omit<React.ComponentProps<typeof ButtonPrimitive>, "children"> & {
  children?: React.ReactNode;
}) {
  const item = React.useContext(NavigationMenuItemContext);

  return (
    <ButtonPrimitive
      aria-expanded={item?.open}
      className={cn(navigationMenuTriggerStyle(), "group", className)}
      data-open={item?.open || undefined}
      data-slot="navigation-menu-trigger"
      onFocus={() => item?.setOpen(true)}
      onHoverStart={() => item?.setOpen(true)}
      onPress={() => item?.setOpen(!item.open)}
      {...props}
    >
      {children}{" "}
      <ChevronDownIcon
        aria-hidden="true"
        className="relative top-px ml-1 size-3 transition duration-300 group-data-popup-open/navigation-menu-trigger:rotate-180 group-data-open/navigation-menu-trigger:rotate-180"
      />
    </ButtonPrimitive>
  );
}

function NavigationMenuContent({
  className,
  ...props
}: React.ComponentProps<"div">) {
  const item = React.useContext(NavigationMenuItemContext);
  const root = React.useContext(NavigationMenuContext);

  const isVisible = root?.visibleItemId === item?.id;
  const isOpen = Boolean(item?.open);

  if (!isVisible) {
    return null;
  }

  const node = (
    <div
      className={cn(
        "top-0 left-0 w-full p-1 ease-[cubic-bezier(0.22,1,0.36,1)] data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95 group-data-[viewport=false]/navigation-menu:top-full group-data-[viewport=false]/navigation-menu:mt-1.5 group-data-[viewport=false]/navigation-menu:overflow-hidden group-data-[viewport=false]/navigation-menu:rounded-lg group-data-[viewport=false]/navigation-menu:bg-popover group-data-[viewport=false]/navigation-menu:text-popover-foreground group-data-[viewport=false]/navigation-menu:shadow group-data-[viewport=false]/navigation-menu:ring-1 group-data-[viewport=false]/navigation-menu:ring-foreground/10 group-data-[viewport=false]/navigation-menu:duration-300 data-[motion=from-end]:slide-in-from-right-52 data-[motion=from-start]:slide-in-from-left-52 data-[motion=to-end]:slide-out-to-right-52 data-[motion=to-start]:slide-out-to-left-52 data-[motion^=from-]:animate-in data-[motion^=from-]:fade-in data-[motion^=to-]:animate-out data-[motion^=to-]:fade-out **:data-[slot=navigation-menu-link]:focus:ring-0 **:data-[slot=navigation-menu-link]:focus:outline-none group-data-[viewport=false]/navigation-menu:md:absolute group-data-[viewport=false]/navigation-menu:md:w-auto group-data-[viewport=true]/navigation-menu:relative group-data-[viewport=true]/navigation-menu:w-max group-data-[viewport=false]/navigation-menu:data-open:animate-in group-data-[viewport=false]/navigation-menu:data-open:fade-in-0 group-data-[viewport=false]/navigation-menu:data-open:zoom-in-95 group-data-[viewport=false]/navigation-menu:data-closed:animate-out group-data-[viewport=false]/navigation-menu:data-closed:fade-out-0 group-data-[viewport=false]/navigation-menu:data-closed:zoom-out-95",
        className,
      )}
      data-closed={isOpen ? undefined : ""}
      data-open={isOpen ? "" : undefined}
      data-slot="navigation-menu-content"
      {...props}
    />
  );

  if (root?.viewport) {
    if (!root.viewportEl) {
      return null;
    }
    return createPortal(node, root.viewportEl);
  }

  return node;
}

function NavigationMenuViewport({
  className,
  ...props
}: React.ComponentProps<"div">) {
  const root = React.useContext(NavigationMenuContext);

  return (
    <div
      className={cn(
        "absolute top-full left-0 isolate z-50 flex justify-center",
      )}
    >
      <div
        ref={root?.setViewportEl}
        className={cn(
          "origin-top-center relative mt-1.5 h-auto w-max overflow-hidden rounded-lg bg-popover text-popover-foreground shadow ring-1 ring-foreground/10 duration-200 data-open:animate-in data-open:zoom-in-90 data-closed:animate-out data-closed:zoom-out-90",
          className,
        )}
        data-closed={root?.visibleItemId && !root.openItemId ? "" : undefined}
        data-open={root?.openItemId ? "" : undefined}
        data-slot="navigation-menu-viewport"
        {...props}
      />
    </div>
  );
}

function NavigationMenuLink({
  className,
  active,
  isCurrent,
  asChild,
  children,
  render,
  ...props
}: React.ComponentProps<typeof LinkPrimitive> & {
  active?: boolean;
  isCurrent?: boolean;
  asChild?: boolean;
}) {
  const current = isCurrent ?? active;

  return (
    <LinkPrimitive
      aria-current={current ? "page" : undefined}
      className={cn(
        "flex items-center gap-2 rounded-lg p-2 text-sm transition-all outline-none hover:bg-muted focus:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-1 in-data-[slot=navigation-menu-content]:rounded-md data-active:bg-muted/50 data-active:hover:bg-muted data-active:focus:bg-muted [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      data-active={current || undefined}
      data-slot="navigation-menu-link"
      render={
        asChild && React.isValidElement(children)
          ? (domProps) =>
              React.cloneElement(
                children as React.ReactElement<Record<string, unknown>>,
                {
                  ...domProps,
                  className: cn(
                    (domProps as { className?: string }).className,
                    (children.props as { className?: string }).className,
                  )},
              )
          : render
      }
      {...props}
    >
      {asChild ? undefined : children}
    </LinkPrimitive>
  );
}

function NavigationMenuIndicator({
  className,
  ...props
}: React.ComponentProps<"div">) {
  const root = React.useContext(NavigationMenuContext);

  if (!root?.openItemId) {
    return null;
  }

  return (
    <div
      className={cn(
        "top-full z-1 flex h-1.5 items-end justify-center overflow-hidden data-[state=hidden]:animate-out data-[state=hidden]:fade-out data-[state=visible]:animate-in data-[state=visible]:fade-in",
        className,
      )}
      data-slot="navigation-menu-indicator"
      {...props}
    >
      <div className="relative top-[60%] h-2 w-2 rotate-45 rounded-tl-sm bg-border shadow-md" />
    </div>
  );
}

export {
  NavigationMenu,
  NavigationMenuList,
  NavigationMenuItem,
  NavigationMenuContent,
  NavigationMenuTrigger,
  NavigationMenuLink,
  NavigationMenuIndicator,
  NavigationMenuViewport,
  navigationMenuTriggerStyle};
