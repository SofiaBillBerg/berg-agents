/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

import {ComponentPreview, Previews} from "@react-buddy/ide-toolbox";
import {PaletteTree} from "./palette";
import App from "../app/App.tsx";
import InputBar from "../app/components/InputBar.tsx";
import MarkdownRenderer from "../app/components/MarkdownRenderer.tsx";
import MessageList from "../app/components/MessageList.tsx";
import ProviderSelector from "../app/components/ProviderSelector.tsx";

const ComponentPreviews = () => {
  return (
    <Previews palette={<PaletteTree />}>
      <ComponentPreview path="/App">
        <App />
      </ComponentPreview>
      <ComponentPreview path="/InputBar">
        <InputBar />
      </ComponentPreview>
      <ComponentPreview path="/MarkdownRenderer">
        <MarkdownRenderer />
      </ComponentPreview>
      <ComponentPreview path="/MessageList">
        <MessageList />
      </ComponentPreview>
      <ComponentPreview path="/ProviderSelector">
        <ProviderSelector />
      </ComponentPreview>
      <ComponentPreview path="/PaletteTree">
        <PaletteTree />
      </ComponentPreview>
    </Previews>
  );
};

export default ComponentPreviews;
