/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // data-terminal 深色 token（.taste-skill/app/direction.json，品牌色映射见 web 前端设计说明）：
        // 地色比面板亮一档（卡片比地面更暗），结构线/行线/控件线三级，文字两档灰（≥4.5:1）
        ground: "#171719", // 页面地色、输入框底
        panel: "#131217", // 卡片/面板（比地色深）
        raised: "#212023", // 悬停、浮层、中性 pill
        line: "#222224", // 结构边线
        rule: "#1b1a1f", // 表格/列表行分隔线（比面板深 3-7%）
        control: "#3a3a3e", // 控件描边（比结构线亮）
        ink: "#f2f2f3", // 主文字
        mut: "#8a8c92", // 次要文字/标签/时间戳
        // 枫叶琥珀：只出现在 1px 选中线、焦点、链接与图表数据上（预算 <3%）
        accent: {
          DEFAULT: "#f59e0b",
          dim: "#b45309",
        },
        pos: "#5fc39c", // positive pill ink / 状态文字
        neg: "#e5566f",
        warn: "#d9a441",
        pill: {
          pos: "#1b2828",
          neg: "#2c1a20",
          warn: "#2a2416",
          neutral: "#212023",
        },
      },
      fontSize: {
        // 应用阶梯（dense：正文 13，标签 12，meta 11，页题 26）——text-sm=13 覆盖默认 14
        "2xs": ["11px", "16px"],
        xs: ["12px", "18px"],
        sm: ["13px", "20px"],
        base: ["14px", "22px"],
        lg: ["16px", "24px"],
        xl: ["20px", "28px"],
        "2xl": ["26px", "32px"],
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        // 只给真正浮起的东西：菜单、弹层、对话框、composer
        pop: "0 12px 28px rgba(0,0,0,.2)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        caret: {
          "0%, 49%": { opacity: "1" },
          "50%, 100%": { opacity: "0" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.18s ease-out",
        caret: "caret 1.1s steps(1) infinite",
      },
    },
  },
  plugins: [],
};
