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
export type {ChatMessage, UseAISDKChatReturn} from "./useAISDKChat";
export type {MessageToolCall} from "./messageParts";

// The ask_user vocabulary and the message-parts walker live in their own
// modules; components keep importing them from the harness barrel.
export type {
    PendingQuestion,
    PendingQuestionAnswer,
    PendingQuestionData,
    PendingQuestionOption} from "./askUser";

// HITL: the approval/question card vocabulary.
export type {PendingApproval} from "./hitl";

// The failure dialog's notice, built by ./recovery.
export type {FailureNotice} from "./recovery";

// The active session id and its storage: one path for every reader and
// writer of that key (chat hook, history page, transport adoption).
export {
    SESSION_ID_KEY,
    forgetStoredSessionId,
    readStoredSessionId,
    storeSessionId} from "./sessionIdentity";
