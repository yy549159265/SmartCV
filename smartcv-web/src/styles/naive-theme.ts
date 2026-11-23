import type { GlobalThemeOverrides } from 'naive-ui'

const FONT_SANS =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI Variable Text', 'Segoe UI', 'PingFang SC', 'HarmonyOS Sans SC', 'Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans SC', sans-serif"

export const themeOverrides: GlobalThemeOverrides = {
  common: {
    fontFamily: FONT_SANS,
    fontSize: '14px',
    fontSizeMini: '11px',
    fontSizeTiny: '12px',
    fontSizeSmall: '13px',
    fontSizeMedium: '14px',
    fontSizeLarge: '15px',
    fontSizeHuge: '17px',

    primaryColor: '#4753c7',
    primaryColorHover: '#3b46b4',
    primaryColorPressed: '#323c9c',
    primaryColorSuppl: '#4753c7',
    infoColor: '#5e7285',
    successColor: '#2f7d52',
    warningColor: '#8f6128',
    errorColor: '#a34640',

    textColorBase: '#181c29',
    textColor1: '#181c29',
    textColor2: '#2a3040',
    textColor3: '#525a6e',
    textColorDisabled: '#a5abbe',
    placeholderColor: '#8f97ab',

    borderColor: '#e2e5ee',
    dividerColor: '#e8eaf1',
    bodyColor: '#f2f4f8',
    cardColor: '#ffffff',
    modalColor: '#ffffff',
    popoverColor: '#ffffff',
    tableColor: '#ffffff',

    hoverColor: 'rgba(71, 83, 199, 0.06)',
    pressedColor: 'rgba(71, 83, 199, 0.1)',
    actionColor: '#f5f6fa',

    borderRadius: '10px',
    borderRadiusSmall: '8px',

    boxShadow1: '0 1px 2px rgba(24, 28, 41, 0.05)',
    boxShadow2: '0 14px 32px -22px rgba(24, 28, 41, 0.24)',
    boxShadow3: '0 26px 60px -30px rgba(24, 28, 41, 0.3)',
  },

  Button: {
    borderRadiusTiny: '6px',
    borderRadiusSmall: '7px',
    borderRadiusMedium: '8px',
    borderRadiusLarge: '10px',
    fontWeight: '500',
    fontWeightStrong: '500',
    textColorText: '#2a3040',
    textColorTextHover: '#181c29',
    textColorTextPressed: '#181c29',
  },

  Card: {
    borderRadius: '14px',
    borderColor: '#e2e5ee',
    color: '#ffffff',
    titleFontWeight: '600',
  },

  Dialog: {
    borderRadius: '16px',
    color: '#ffffff',
    titleFontSize: '17px',
    titleFontWeight: '600',
  },

  Input: {
    borderRadius: '8px',
    color: '#ffffff',
    colorFocus: '#ffffff',
    border: '1px solid #e2e5ee',
    borderHover: '1px solid #c3c9d8',
    borderFocus: '1px solid #4753c7',
    boxShadowFocus: '0 0 0 3px rgba(71, 83, 199, 0.12)',
    placeholderColor: '#8f97ab',
  },

  InputNumber: {
    borderRadius: '8px',
    border: '1px solid #e2e5ee',
    borderHover: '1px solid #c3c9d8',
    borderFocus: '1px solid #4753c7',
    boxShadowFocus: '0 0 0 3px rgba(71, 83, 199, 0.12)',
  },

  Select: {
    peers: {
      InternalSelection: {
        borderRadius: '8px',
        border: '1px solid #e2e5ee',
        borderHover: '1px solid #c3c9d8',
        borderFocus: '1px solid #4753c7',
        borderActive: '1px solid #4753c7',
        boxShadowFocus: '0 0 0 3px rgba(71, 83, 199, 0.12)',
        boxShadowActive: '0 0 0 3px rgba(71, 83, 199, 0.12)',
      },
      InternalSelectMenu: {
        borderRadius: '12px',
        optionColorPending: '#eef0fb',
        optionTextColorActive: '#3b46b4',
      },
    },
  },

  Switch: {
    railColor: '#dfe2ea',
    railColorActive: '#4753c7',
    buttonColor: '#ffffff',
    buttonBoxShadow: '0 1px 2px rgba(24, 28, 41, 0.14)',
  },

  Slider: {
    fillColor: '#4753c7',
    fillColorHover: '#3b46b4',
    railColor: '#e2e5ee',
    railColorHover: '#ccd1de',
    handleColor: '#ffffff',
    handleBoxShadow: '0 0 0 1px #cdd1dd, 0 1px 3px rgba(24, 28, 41, 0.12)',
    handleBoxShadowHover: '0 0 0 1px #4753c7, 0 1px 4px rgba(24, 28, 41, 0.16)',
    handleBoxShadowActive: '0 0 0 1px #4753c7, 0 1px 4px rgba(24, 28, 41, 0.16)',
    handleBoxShadowFocus: '0 0 0 3px rgba(71, 83, 199, 0.16)',
    indicatorColor: '#3b46b4',
    indicatorTextColor: '#ffffff',
    markTextColor: '#798196',
  },

  Tag: {
    borderRadius: '999px',
    color: '#f3f5fc',
    colorBordered: '#ffffff',
    border: '1px solid #e2e5ee',
    textColor: '#2a3040',
    textColorBordered: '#2a3040',
  },

  Checkbox: {
    borderRadius: '4px',
    colorChecked: '#4753c7',
    borderChecked: '1px solid #4753c7',
    borderFocus: '1px solid #4753c7',
    boxShadowFocus: '0 0 0 3px rgba(71, 83, 199, 0.12)',
  },

  Radio: {
    borderRadius: '999px',
    buttonBorderRadius: '7px',
    buttonColor: '#ffffff',
    buttonColorActive: '#eceffb',
    buttonTextColor: '#525a6e',
    buttonTextColorActive: '#3b46b4',
    color: '#ffffff',
    colorChecked: '#4753c7',
    boxShadowFocus: '0 0 0 3px rgba(71, 83, 199, 0.12)',
  },

  Popover: {
    borderRadius: '12px',
    boxShadow: '0 20px 48px -26px rgba(24, 28, 41, 0.3)',
  },

  Tooltip: {
    borderRadius: '8px',
    color: '#242a3a',
    textColor: '#f5f6fa',
  },

  Message: {
    borderRadius: '10px',
    boxShadow: '0 14px 34px -20px rgba(24, 28, 41, 0.28)',
  },

  Form: {
    labelFontSize: '13px',
    labelTextColor: '#525a6e',
    labelFontWeight: '500',
  },

  Collapse: {
    titleFontWeight: '600',
  },
}
