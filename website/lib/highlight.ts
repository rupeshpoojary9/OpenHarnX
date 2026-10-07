// Code colours: GitHub's themes, with the token colours that fall under 4.5:1 on this
// site's code backgrounds (#ebe7df light, #131a1c dark) darkened or lightened just
// enough. Computed from the themes' own colours; recompute if the backgrounds change.
export const codeThemes = { light: "github-light", dark: "github-dark" } as const;

export const colorReplacements = {
  "github-light": {
    "#6a737d": "#5d656e", // comments
    "#22863a": "#1e7633",
    "#d73a49": "#b9323f", // keywords
    "#e36209": "#a84907",
  },
  "github-dark": {
    "#6a737d": "#7c848d", // comments
  },
};
