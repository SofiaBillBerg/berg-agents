import React from "react";

class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = {hasError: false, error: null};
    }

    static getDerivedStateFromError(error) {
        return {hasError: true, error};
    }

    componentDidCatch(error, errorInfo) {
        console.error("React error boundary caught:", error, errorInfo);
    }

    render() {
        if (this.state.hasError) {
            return (
                <div style={{padding: "2rem", color: "red", fontFamily: "monospace"}}>
                    <h2>Something went wrong</h2>
                    <pre style={{whiteSpace: "pre-wrap", fontSize: "0.8rem"}}>
                        {this.state.error?.toString()}
                        {"\n\n"}
                        {this.state.error?.stack}
                    </pre>
                </div>
            );
        }
        return this.props.children;
    }
}

export default ErrorBoundary;
