/*
 * Harness provider component that manages harness connection and provides it to children.
 * This replaces the complex useBergHarness hook with a simple context-based approach.
 */

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

import { IHarness, HarnessEvent, TaskResult, HitlRequest } from './webhook';
import { RealHarness } from './real-harness';
import { MockHarness } from './mock-harness';

interface HarnessContextValue {
  harness: IHarness | null;
  isConnected: boolean;
  isLoading: boolean;
  error: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
  setHarnessMode: (mode: 'real' | 'mock') => void;
  setMockScenario: (scenario: 'success' | 'failure' | 'hitl_required' | 'long_running') => void;
}

const HarnessContext = createContext<HarnessContextValue | null>(null);

interface HarnessProviderProps {
  children: ReactNode;
  initialMode?: 'real' | 'mock';
  initialScenario?: 'success' | 'failure' | 'hitl_required' | 'long_running';
}

export function HarnessProvider({ 
  children, 
  initialMode = 'real',
  initialScenario = 'success'
}: HarnessProviderProps) {
  const [harness, setHarness] = useState<IHarness | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<'real' | 'mock'>(initialMode);
  const [mockScenario, setMockScenario] = useState<'success' | 'failure' | 'hitl_required' | 'long_running'>(initialScenario);
  
  // Initialize harness based on mode
  useEffect(() => {
    const initHarness = async () => {
      setIsLoading(true);
      setError(null);
      
      try {
        if (mode === 'mock') {
          // Use mock harness for testing/development
          const mock = new MockHarness(mockScenario);
          setHarness(mock);
          setIsConnected(true);
        } else {
          // Use real harness (connect to Python backend)
          const real = new RealHarness();
          setHarness(real);
          
          // Check connection status
          const connected = real.isConnected();
          setIsConnected(connected);
          
          if (!connected) {
            setError('Failed to connect to backend harness');
          }
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to initialize harness';
        setError(errorMessage);
        console.error('Harness initialization error:', err);
      } finally {
        setIsLoading(false);
      }
    };
    
    initHarness();
    
    // Cleanup on unmount
    return () => {
      if (harness instanceof RealHarness) {
        harness.destroy();
      }
      setHarness(null);
      setIsConnected(false);
    };
  }, [mode, mockScenario]);
  
  // Update mock scenario when mode changes
  useEffect(() => {
    if (mode === 'mock' && harness instanceof MockHarness) {
      harness.setScenario(mockScenario);
    }
  }, [mode, mockScenario, harness]);
  
  const connect = async () => {
    if (!harness) return;
    
    setIsLoading(true);
    setError(null);
    
    try {
      if (harness instanceof RealHarness) {
        harness.reconnect();
        setIsConnected(harness.isConnected());
      } else {
        setIsConnected(true);
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Connection failed';
      setError(errorMessage);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };
  
  const disconnect = () => {
    if (harness instanceof RealHarness) {
      harness.destroy();
    }
    setHarness(null);
    setIsConnected(false);
    setError(null);
  };
  
  const updateMode = (newMode: 'real' | 'mock') => {
    setMode(newMode);
  };
  
  const updateMockScenario = (scenario: 'success' | 'failure' | 'hitl_required' | 'long_running') => {
    setMockScenario(scenario);
    if (mode === 'mock' && harness instanceof MockHarness) {
      harness.setScenario(scenario);
    }
  };
  
  const value: HarnessContextValue = {
    harness,
    isConnected,
    isLoading,
    error,
    connect,
    disconnect,
    setHarnessMode: updateMode,
    setMockScenario: updateMockScenario,
  };
  
  return (
    <HarnessContext.Provider value={value}>
      {children}
    </HarnessContext.Provider>
  );
}

// Custom hook to use the harness context
export function useHarness() {
  const context = useContext(HarnessContext);
  
  if (context === null) {
    throw new Error('useHarness must be used within a HarnessProvider');
  }
  
  return context;
}

// Higher-order component for components that need harness
export function withHarness<T extends { harness?: IHarness | null }>(Component: React.ComponentType<T>) {
  return function WithHarnessComponent(props: Omit<T, 'harness'>) {
    const { harness } = useHarness();
    
    return <Component {...(props as T)} harness={harness} />;
  };
}