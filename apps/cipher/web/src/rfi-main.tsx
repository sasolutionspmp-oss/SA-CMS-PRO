import { createRoot } from 'react-dom/client';
import { FluentProvider } from '@fluentui/react-components';
import { createDOMRenderer, RendererProvider } from '@griffel/react';
import { cipherTheme } from './theme/theme';
import { RFIApp } from './rfi/App';

const nonce = document.querySelector<HTMLMetaElement>('meta[name="cipher-style-nonce"]')?.content;
const renderer = createDOMRenderer(document, { styleElementAttributes: nonce && nonce !== '__CIPHER_STYLE_NONCE__' ? { nonce } : {} });
const root = document.getElementById('root');
if (!root) throw new Error('The application root is missing.');
createRoot(root).render(<RendererProvider renderer={renderer}><FluentProvider theme={cipherTheme}><RFIApp /></FluentProvider></RendererProvider>);
