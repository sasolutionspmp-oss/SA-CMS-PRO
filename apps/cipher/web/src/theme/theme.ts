import { createLightTheme, type BrandVariants, type Theme } from '@fluentui/react-components';

export const brandNavy = '#0B2341';
// The owner must confirm the final brand file before this becomes a production color.
export const accentPlaceholder = '#9FD93A';

// Generated with Microsoft's Fluent Theme Designer getBrandTokensFromPalette:
// keyColor #0B2341, darkCp 2/3, lightCp 1/3, hueTorsion 0 (16-step Lab curve).
// The generated curve does not place the input key at a fixed step. Exact brand
// roles below keep the S&A frame, links, and primary controls consistently navy.
const navyRamp: BrandVariants = {
  10: '#00030C',
  20: '#031831',
  30: '#0F2644',
  40: '#1D3151',
  50: '#2B3E5D',
  60: '#394A69',
  70: '#475775',
  80: '#566482',
  90: '#64718E',
  100: '#737F9A',
  110: '#838DA5',
  120: '#929CB1',
  130: '#A2AABD',
  140: '#B2B9C9',
  150: '#C3C8D5',
  160: '#D3D7E1',
};

const interfaceFont = '"Segoe UI Variable", "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, system-ui, sans-serif';

export const cipherTheme: Theme = {
  ...createLightTheme(navyRamp),
  fontFamilyBase: interfaceFont,
  fontFamilyNumeric: interfaceFont,
  colorBrandBackground: brandNavy,
  colorBrandBackgroundHover: '#13325A',
  colorBrandBackgroundPressed: '#07182F',
  colorBrandBackgroundSelected: brandNavy,
  colorBrandBackground2: '#E8EDF4',
  colorBrandBackground2Hover: '#DDE5EF',
  colorBrandBackground2Pressed: '#D2DDEB',
  colorBrandForeground1: brandNavy,
  colorBrandForeground2: brandNavy,
  colorBrandForeground2Hover: '#13325A',
  colorBrandForeground2Pressed: '#07182F',
  colorBrandForegroundLink: '#1A56A8',
  colorBrandForegroundLinkHover: '#13325A',
  colorBrandForegroundLinkPressed: '#07182F',
  colorBrandForegroundLinkSelected: brandNavy,
  colorBrandStroke1: brandNavy,
  colorBrandStroke2: '#E8EDF4',
  colorNeutralForeground1: '#131E29',
  colorNeutralForeground2: '#556B82',
  colorNeutralForeground3: '#556B82',
  colorNeutralBackground1: '#FFFFFF',
  colorNeutralBackground2: '#F5F6F7',
  colorNeutralBackground3: '#EEF1F4',
  colorNeutralStroke1: '#E3E6EA',
  colorNeutralStroke2: '#E3E6EA',
  colorNeutralStrokeAccessible: '#7A8794',
  colorNeutralStrokeAccessibleHover: '#556B82',
  colorNeutralStrokeAccessiblePressed: brandNavy,
  colorNeutralStrokeAccessibleSelected: brandNavy,
  colorStrokeFocus2: brandNavy,
  colorPaletteGreenForeground1: '#256F3A',
  colorPaletteGreenBackground1: '#E8F3EC',
  colorPaletteDarkOrangeForeground1: '#8A4B00',
  colorPaletteDarkOrangeBackground1: '#FFF4E5',
  colorPaletteRedForeground1: '#AA0808',
  colorPaletteRedBackground1: '#FDECEC',
  borderRadiusSmall: '4px',
  borderRadiusMedium: '4px',
  borderRadiusLarge: '6px',
  borderRadiusXLarge: '6px',
};
