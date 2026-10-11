/*
 * <one line to give the program's name and a brief idea of what it does.>
 *
 * Copyright (c) 2026.
 *         Copyright (C) <year>  <name of author>
 *
 *         This program is free software: you can redistribute it and/or modify
 *         it under the terms of the GNU Affero General Public License as
 *         published by the Free Software Foundation, either version 3 of the
 *         License, or (at your option) any later version.
 *
 *         This program is distributed in the hope that it will be useful,
 *         but WITHOUT ANY WARRANTY; without even the implied warranty of
 *         MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *         GNU Affero General Public License for more details.
 *
 *         You should have received a copy of the GNU Affero General Public License
 *         along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 */

/*
 * Barrel export for the harness module.
 * Simplified - uses AI SDK v7's useChat directly, no custom harness classes.
 */

// Re-export types used by components.
export type {
  AgentInfo,
  HitlRequest,
  TaskResult,
  HarnessEvent,
  HitlDecisionInput} from "./webhook";

// Main chat hook - wraps AI SDK v7's useChat.
export { useAISDKChat } from "./useAISDKChat";
export type {
  ChatMessage,
  PendingApproval,
  UseAISDKChatReturn} from "./useAISDKChat";
