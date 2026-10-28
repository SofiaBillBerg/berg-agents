/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
* The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 *
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
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
export {useAISDKChat} from "./useAISDKChat";
export type {
    ChatMessage,
    PendingApproval,
    UseAISDKChatReturn} from "./useAISDKChat";
