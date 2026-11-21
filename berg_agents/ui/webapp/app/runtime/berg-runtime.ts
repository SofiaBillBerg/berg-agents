"use client";

import * as React from "react";
import * as ReactJSXRuntime from "react/jsx-runtime";
import * as ReactDOM from "react-dom";
import * as ReactDOMClient from "react-dom/client";
import * as Streamdown from "streamdown";

import * as Alert from "@/components/ui/alert";
import * as Avatar from "@/components/ui/avatar";
import * as Badge from "@/components/ui/badge";
import * as Button from "@/components/ui/button";
import * as Card from "@/components/ui/card";
import * as Dialog from "@/components/ui/dialog";
import * as Field from "@/components/ui/field";
import * as Input from "@/components/ui/input";
import * as Progress from "@/components/ui/progress";
import * as Select from "@/components/ui/select";
import * as Separator from "@/components/ui/separator";
import * as Spinner from "@/components/ui/spinner";
import * as Switch from "@/components/ui/switch";
import * as Textarea from "@/components/ui/textarea";
import * as Tooltip from "@/components/ui/tooltip";
import { API_BASE } from "@/envConfig";

/** Modules a plugin bundle may resolve through the runtime. */
const RUNTIME_MODULES: Record<string, unknown> = {
  react: React,
  "react/jsx-runtime": ReactJSXRuntime,
  "react/jsx-dev-runtime": ReactJSXRuntime,
  "react-dom": ReactDOM,
  "react-dom/client": ReactDOMClient,
  streamdown: Streamdown,
  "@/components/ui/alert": Alert,
  "@/components/ui/avatar": Avatar,
  "@/components/ui/badge": Badge,
  "@/components/ui/button": Button,
  "@/components/ui/card": Card,
  "@/components/ui/dialog": Dialog,
  "@/components/ui/field": Field,
  "@/components/ui/input": Input,
  "@/components/ui/progress": Progress,
  "@/components/ui/select": Select,
  "@/components/ui/separator": Separator,
  "@/components/ui/spinner": Spinner,
  "@/components/ui/switch": Switch,
  "@/components/ui/textarea": Textarea,
  "@/components/ui/tooltip": Tooltip};

interface BergRuntimeGlobal {
  React: typeof React;
  apiBase: string;
  sessionId: string;
  require: (specifier: string) => unknown;
}

declare global {
  interface Window {
    BergRuntime?: BergRuntimeGlobal;
  }
}

export function setRuntimeSessionId(sessionId: string): void {
  if (typeof window === "undefined" || !window.BergRuntime) return;
  window.BergRuntime.sessionId = String(sessionId ?? "");
}

export function installBergRuntime(): void {
  if (typeof window === "undefined" || window.BergRuntime) return;
  window.BergRuntime = {
    React,
    apiBase: API_BASE,
    sessionId: "",
    require: (specifier: string) => {
      const mod = RUNTIME_MODULES[specifier];
      if (mod === undefined) {
        throw new Error(
          `Plugin UI imported "${specifier}", which the host runtime does ` +
            `not expose. Add it to RUNTIME_MODULES in ` +
            `app/runtime/berg-runtime.ts.`,
        );
      }
      return mod;
    }};
}
