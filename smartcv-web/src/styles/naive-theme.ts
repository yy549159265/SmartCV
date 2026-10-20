/**
 * Naive UI 主题覆盖
 *
 * 只影响外观：把组件库默认的亮绿主色、较硬的阴影和圆角，
 * 统一到应用的「瓷白 + 苔绿」色板上，让 n-button / n-input / 弹窗
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

    primaryColor: '#4b6b5e',
    primaryColorHover: '#5c7d6f',
    primaryColorPressed: '#3e5a4f',
    primaryColorSuppl: '#4b6b5e',
    infoColor: '#5e7285',
    successColor: '#4b6b5e',
    warningColor: '#a6763f',
    errorColor: '#a94f4a',

    textColorBase: '#242a26',
    textColor1: '#242a26',
    textColor2: '#3f4742',
    textColor3: '#6f786f',
    textColorDisabled: '#a5ada5',
    placeholderColor: '#98a099',

    borderColor: '#e3e6df',
    dividerColor: '#e9ece6',
    bodyColor: '#f2f3f0',
    cardColor: '#ffffff',
    modalColor: '#ffffff',
    popoverColor: '#ffffff',
    tableColor: '#ffffff',

    hoverColor: 'rgba(75, 107, 94, 0.06)',
    pressedColor: 'rgba(75, 107, 94, 0.1)',
    actionColor: '#f4f6f2',

    borderRadius: '10px',
    borderRadiusSmall: '7px',

    boxShadow1: '0 1px 2px rgba(36, 42, 38, 0.05)',
    boxShadow2: '0 10px 28px -16px rgba(36, 42, 38, 0.22)',
    boxShadow3: '0 24px 56px -28px rgba(36, 42, 38, 0.28)',
  },

  Button: {
    borderRadiusTiny: '5px',
    borderRadiusSmall: '7px',
    borderRadiusMedium: '9px',
    borderRadiusLarge: '11px',
    fontWeight: '500',
    textColorText: '#3f4742',
    textColorTextHover: '#242a26',
    textColorTextPressed: '#242a26',
  },

  Card: {
    borderRadius: '16px',
    borderColor: '#e3e6df',
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
    border: '1px solid #e3e6df',
    borderHover: '1px solid #c9cfc6',
    borderFocus: '1px solid #4b6b5e',
    boxShadowFocus: '0 0 0 2px rgba(75, 107, 94, 0.12)',
    placeholderColor: '#98a099',
  },

  InputNumber: {
    borderRadius: '9px',
    border: '1px solid #e3e6df',
    borderHover: '1px solid #c9cfc6',
    borderFocus: '1px solid #4b6b5e',
    boxShadowFocus: '0 0 0 2px rgba(75, 107, 94, 0.12)',
  },

  Select: {
    peers: {
      InternalSelection: {
        borderRadius: '9px',
        border: '1px solid #e3e6df',
        borderHover: '1px solid #c9cfc6',
        borderFocus: '1px solid #4b6b5e',
        borderActive: '1px solid #4b6b5e',
        boxShadowFocus: '0 0 0 2px rgba(75, 107, 94, 0.12)',
        boxShadowActive: '0 0 0 2px rgba(75, 107, 94, 0.12)',
      },
      InternalSelectMenu: {
        borderRadius: '12px',
        optionColorPending: '#eef3ef',
        optionTextColorActive: '#3e5a4f',
      },
    },
  },

  Switch: {
    railColor: '#dfe3dc',
    railColorActive: '#4b6b5e',
    buttonColor: '#ffffff',
    buttonBoxShadow: '0 1px 2px rgba(36, 42, 38, 0.14)',
  },

  Slider: {
    fillColor: '#4b6b5e',
    fillColorHover: '#5c7d6f',
    railColor: '#e3e6df',
    railColorHover: '#d2d7cf',
    handleColor: '#ffffff',
    handleBoxShadow: '0 0 0 1px #cfd5cd, 0 1px 3px rgba(36, 42, 38, 0.12)',
    handleBoxShadowHover: '0 0 0 1px #4b6b5e, 0 1px 4px rgba(36, 42, 38, 0.16)',
    handleBoxShadowActive: '0 0 0 1px #4b6b5e, 0 1px 4px rgba(36, 42, 38, 0.16)',
    handleBoxShadowFocus: '0 0 0 3px rgba(75, 107, 94, 0.16)',
    indicatorColor: '#3e5a4f',
    indicatorTextColor: '#ffffff',
    markTextColor: '#8b938c',
  },

  Tag: {
    borderRadius: '999px',
    color: '#f1f5f2',
    colorBordered: '#ffffff',
    border: '1px solid #e3e6df',
    textColor: '#3f4742',
    textColorBordered: '#3f4742',
  },

  Checkbox: {
    borderRadius: '4px',
    colorChecked: '#4b6b5e',
    borderChecked: '1px solid #4b6b5e',
    borderFocus: '1px solid #4b6b5e',
    boxShadowFocus: '0 0 0 2px rgba(75, 107, 94, 0.12)',
  },

  Radio: {
    borderRadius: '999px',
    buttonBorderRadius: '7px',
    buttonColor: '#ffffff',
    buttonColorActive: '#e8efea',
    buttonTextColor: '#5f6862',
    buttonTextColorActive: '#3e5a4f',
    color: '#ffffff',
    colorChecked: '#4b6b5e',
    boxShadowFocus: '0 0 0 2px rgba(75, 107, 94, 0.12)',
  },

  Popover: {
    borderRadius: '12px',
    // 不要在这里设 color：NTooltip 内部会把自己的 Popover 主题覆盖传给 NPopover，
    // 这里的白色会压过 Tooltip 的深色底，出现「白色浮层 + 白字」的空白提示框。
    // 弹层默认就是白色（common.popoverColor），无需重复声明。
    boxShadow: '0 18px 44px -24px rgba(36, 42, 38, 0.3)',
  },

  Tooltip: {
    borderRadius: '8px',
    color: '#2f3732',
    textColor: '#f4f6f2',
  },

  Message: {
    borderRadius: '10px',
    boxShadow: '0 12px 32px -18px rgba(36, 42, 38, 0.28)',
  },

  Form: {
    labelFontSize: '12px',
    labelTextColor: '#5f6862',
    labelFontWeight: '500',
  },

  Collapse: {
    titleFontWeight: '600',
  },
}
