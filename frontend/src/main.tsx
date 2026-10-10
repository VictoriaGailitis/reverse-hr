import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { DemoProvider } from './state/DemoContext';
import { BackendProvider } from './state/BackendProvider';
import './styles/tokens.css';
import './styles/app.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><BrowserRouter><BackendProvider><DemoProvider><App /></DemoProvider></BackendProvider></BrowserRouter></React.StrictMode>,
);
