/**
 * Naive UI 主题覆盖
 *
 * 只影响外观：把组件库默认的亮绿主色、较硬的阴影和圆角，
 * 统一到应用的「冷灰 + 靛蓝」色板上，让 n-button / n-input / 弹窗
 * 与自绘界面看起来是同一套东西。所有业务逻辑、尺寸逻辑都不在这里改。
 */
import type { GlobalThemeOverrides } from 'naive-ui'

const FONT_SANS =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif"

export const themeOverrides: GlobalThemeOverrides = {
  common: {
    fontFamily: FONT_SANS,
    fontSize: '13px',
    fontSizeMini: '11px',
    fontSizeTiny: '12px',
    fontSizeSmall: '12px',
    fontSizeMedium: '13px',
    fontSizeLarge: '14px',
    fontSizeHuge: '16px',

    primaryColor: '#4753c7',
    primaryColorHover: '#5b66d2',
    primaryColorPressed: '#3c46b2',
    primaryColorSuppl: '#4753c7',
    infoColor: '#5e7285',
    successColor: '#3f8f5a',
    warningColor: '#a6763f',
    errorColor: '#a94f4a',

    textColorBase: '#1c2130',
    textColor1: '#1c2130',
    textColor2: '#2a3040',
    textColor3: '#596175',
    textColorDisabled: '#a5abbe',
    placeholderColor: '#98a0b3',

    borderColor: '#e4e6ec',
    dividerColor: '#e9ebf0',
    bodyColor: '#f6f7f9',
    cardColor: '#ffffff',
    modalColor: '#ffffff',
    popoverColor: '#ffffff',
    tableColor: '#ffffff',

    hoverColor: 'rgba(71, 83, 199, 0.06)',
    pressedColor: 'rgba(71, 83, 199, 0.1)',
    actionColor: '#f4f5f8',

    borderRadius: '10px',
    borderRadiusSmall: '7px',

    boxShadow1: '0 1px 2px rgba(28, 33, 48, 0.05)',
    boxShadow2: '0 12px 28px -18px rgba(28, 33, 48, 0.22)',
    boxShadow3: '0 24px 56px -28px rgba(28, 33, 48, 0.3)',
  },

  Button: {
    borderRadiusTiny: '5px',
    borderRadiusSmall: '7px',
    borderRadiusMedium: '9px',
    borderRadiusLarge: '11px',
    fontWeight: '500',
    textColorText: '#2a3040',
    textColorTextHover: '#1c2130',
    textColorTextPressed: '#1c2130',
  },

  Card: {
    borderRadius: '16px',
    borderColor: '#e4e6ec',
    color: '#ffffff',
    titleFontWeight: '600',
  },

  Dialog: {
    borderRadius: '16px',
    color: '#ffffff',
    titleFontSize: '16px',
    titleFontWeight: '600',
  },

  Input: {
    borderRadius: '9px',
    color: '#ffffff',
    colorFocus: '#ffffff',
    border: '1px solid #e4e6ec',
    borderHover: '1px solid #c9cdd9',
    borderFocus: '1px solid #4753c7',
    boxShadowFocus: '0 0 0 2px rgba(71, 83, 199, 0.12)',
    placeholderColor: '#98a0b3',
  },

  InputNumber: {
    borderRadius: '9px',
    border: '1px solid #e4e6ec',
    borderHover: '1px solid #c9cdd9',
    borderFocus: '1px solid #4753c7',
    boxShadowFocus: '0 0 0 2px rgba(71, 83, 199, 0.12)',
  },

  Select: {
    peers: {
      InternalSelection: {
        borderRadius: '9px',
        border: '1px solid #e4e6ec',
        borderHover: '1px solid #c9cdd9',
        borderFocus: '1px solid #4753c7',
        borderActive: '1px solid #4753c7',
        boxShadowFocus: '0 0 0 2px rgba(71, 83, 199, 0.12)',
        boxShadowActive: '0 0 0 2px rgba(71, 83, 199, 0.12)',
      },
      InternalSelectMenu: {
        borderRadius: '12px',
        optionColorPending: '#eef0fb',
        optionTextColorActive: '#3c46b2',
      },
    },
  },

  Switch: {
    railColor: '#dfe2ea',
    railColorActive: '#4753c7',
    buttonColor: '#ffffff',
    buttonBoxShadow: '0 1px 2px rgba(28, 33, 48, 0.14)',
  },

  Slider: {
    fillColor: '#4753c7',
    fillColorHover: '#5b66d2',
    railColor: '#e4e6ec',
    railColorHover: '#d3d6df',
    handleColor: '#ffffff',
    handleBoxShadow: '0 0 0 1px #cdd1dd, 0 1px 3px rgba(28, 33, 48, 0.12)',
    handleBoxShadowHover: '0 0 0 1px #4753c7, 0 1px 4px rgba(28, 33, 48, 0.16)',
    handleBoxShadowActive: '0 0 0 1px #4753c7, 0 1px 4px rgba(28, 33, 48, 0.16)',
    handleBoxShadowFocus: '0 0 0 3px rgba(71, 83, 199, 0.16)',
    indicatorColor: '#3c46b2',
    indicatorTextColor: '#ffffff',
    markTextColor: '#8a91a6',
  },

  Tag: {
    borderRadius: '999px',
    color: '#f4f5fc',
    colorBordered: '#ffffff',
    border: '1px solid #e4e6ec',
    textColor: '#2a3040',
    textColorBordered: '#2a3040',
  },

  Checkbox: {
    borderRadius: '4px',
    colorChecked: '#4753c7',
    borderChecked: '1px solid #4753c7',
    borderFocus: '1px solid #4753c7',
    boxShadowFocus: '0 0 0 2px rgba(71, 83, 199, 0.12)',
  },

  Radio: {
    borderRadius: '999px',
    buttonBorderRadius: '7px',
    buttonColor: '#ffffff',
    buttonColorActive: '#eceffb',
    buttonTextColor: '#596175',
    buttonTextColorActive: '#3c46b2',
    color: '#ffffff',
    colorChecked: '#4753c7',
    boxShadowFocus: '0 0 0 2px rgba(71, 83, 199, 0.12)',
  },

  Popover: {
    borderRadius: '12px',
    // 不要在这里设 color：NTooltip 内部会把自己的 Popover 主题覆盖传给 NPopover，
    // 这里的白色会压过 Tooltip 的深色底，出现「白色浮层 + 白字」的空白提示框。
    // 弹层默认就是白色（common.popoverColor），无需重复声明。
    boxShadow: '0 18px 44px -24px rgba(28, 33, 48, 0.28)',
  },

  Tooltip: {
    borderRadius: '8px',
    color: '#262c3f',
    textColor: '#f4f5f8',
  },

  Message: {
    borderRadius: '10px',
    boxShadow: '0 12px 32px -18px rgba(28, 33, 48, 0.26)',
  },

  Form: {
    labelFontSize: '12px',
    labelTextColor: '#596175',
    labelFontWeight: '500',
  },

  Collapse: {
    titleFontWeight: '600',
  },
}
