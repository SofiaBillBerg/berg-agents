import {ComponentPreview, Previews} from '@react-buddy/ide-toolbox'
import {PaletteTree} from './palette'
import App from "../app/App.tsx";
import InputBar from "../app/components/InputBar.tsx";
import MarkdownRenderer from "../app/components/MarkdownRenderer.tsx";
import MessageList from "../app/components/MessageList.tsx";
import ProviderSelector from "../app/components/ProviderSelector.tsx";
import SubagentCard from "../app/components/SubagentCard.tsx";
import ThreadHistory from "../app/components/ThreadHistory.tsx";
import TodoList from "../app/components/TodoList.tsx";
import ToolCallRow from "../app/components/ToolCallRow.tsx";

const ComponentPreviews = () => {
    return (
        <Previews palette={<PaletteTree/>}>
            <ComponentPreview path="/App">
                <App/>
            </ComponentPreview>
            <ComponentPreview path="/InputBar">
                <InputBar/>
            </ComponentPreview>
            <ComponentPreview path="/MarkdownRenderer">
                <MarkdownRenderer/>
            </ComponentPreview>
            <ComponentPreview path="/MessageList">
                <MessageList/>
            </ComponentPreview>
            <ComponentPreview path="/ProviderSelector">
                <ProviderSelector/>
            </ComponentPreview>
            <ComponentPreview path="/SubagentCard">
                <SubagentCard/>
            </ComponentPreview>
            <ComponentPreview path="/ThreadHistory">
                <ThreadHistory/>
            </ComponentPreview>
            <ComponentPreview path="/TodoList">
                <TodoList/>
            </ComponentPreview>
            <ComponentPreview path="/ToolCallRow">
                <ToolCallRow/>
            </ComponentPreview>
            <ComponentPreview path="/PaletteTree">
                <PaletteTree/>
            </ComponentPreview>
        </Previews>
    )
}

export default ComponentPreviews
