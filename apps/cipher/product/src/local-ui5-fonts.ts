import { setDefaultFontLoading } from '@ui5/webcomponents-base/dist/config/Fonts.js';
import '@ui5/webcomponents-base/dist/FontFace.css';

// Vite bundles the official CSS's pinned SAP 72 package URLs as same-origin
// assets. Disable UI5's automatic CDN declarations before component boot.
setDefaultFontLoading(false);
const license = document.createElement('link');
license.rel = 'license';
license.href = new URL('../node_modules/@sap-theming/theming-base-content/LICENSE.txt', import.meta.url).href;
document.head.append(license);
