import { Palette as PaletteIcon } from "lucide-react";
import { useEffect, useState } from "react";
import {
  ArrowToolbarItem,
  DefaultStylePanel,
  DrawToolbarItem,
  EraserToolbarItem,
  HandToolbarItem,
  HighlightToolbarItem,
  RectangleToolbarItem,
  SelectToolbarItem,
  StylePanelColorPicker,
  StylePanelDashPicker,
  StylePanelFillPicker,
  StylePanelOpacityPicker,
  StylePanelSection,
  StylePanelSizePicker,
  TextToolbarItem,
  TldrawUiMenuContextProvider,
  TldrawUiToolbar,
  TldrawUiToolbarButton,
  useEditor,
  useValue,
} from "tldraw";

function PaletteOptions() {
  const editor = useEditor();
  const [hasSelection, setHasSelection] = useState(
    () => editor.getSelectedShapeIds().length > 0,
  );

  useEffect(() => {
    const updateSelection = () => {
      const next = editor.getSelectedShapeIds().length > 0;
      setHasSelection((current) => (current === next ? current : next));
    };
    updateSelection();
    return editor.store.listen(updateSelection);
  }, [editor]);

  return (
    <div className="sidebar-style-panel w-52 rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
      <DefaultStylePanel isMobile>
        <StylePanelSection>
          <StylePanelColorPicker />
          <StylePanelOpacityPicker />
        </StylePanelSection>
        {hasSelection ? (
          <StylePanelSection>
            <StylePanelFillPicker />
            <StylePanelDashPicker />
          </StylePanelSection>
        ) : null}
        <StylePanelSection>
          <StylePanelSizePicker />
        </StylePanelSection>
      </DefaultStylePanel>
    </div>
  );
}

export function WhiteboardToolbar() {
  const editor = useEditor();
  const currentTool = useValue(
    "canvas-toolbar-tool",
    () => editor.getCurrentToolId(),
    [editor],
  );
  const paletteAvailable = currentTool !== "eraser";
  const [paletteOpen, setPaletteOpen] = useState(false);
  const showPalette = paletteOpen && paletteAvailable;

  return (
    <>
      <TldrawUiToolbar
        className="mentora-drawing-toolbar absolute! left-4! top-1/2! z-40! -translate-y-1/2!"
        label="Drawing tools"
        orientation="vertical"
        tooltipSide="right"
      >
        <TldrawUiMenuContextProvider sourceId="toolbar" type="toolbar">
          <SelectToolbarItem />
          <HandToolbarItem />
          <DrawToolbarItem />
          <HighlightToolbarItem />
          <TextToolbarItem />
          <ArrowToolbarItem />
          <RectangleToolbarItem />
          <EraserToolbarItem />
          <TldrawUiToolbarButton
            className="hover:cursor-grab"
            disabled={!paletteAvailable}
            isActive={showPalette}
            onClick={() => setPaletteOpen((current) => !current)}
            title={showPalette ? "Close palette" : "Open palette"}
            type="tool"
            tooltip={showPalette ? "Close palette" : "Open palette"}
          >
            <PaletteIcon aria-hidden="true" className="size-4" />
          </TldrawUiToolbarButton>
        </TldrawUiMenuContextProvider>
      </TldrawUiToolbar>
      {showPalette ? (
        <button
          aria-label="Close palette"
          className="fixed inset-0 z-30 cursor-default"
          onClick={() => setPaletteOpen(false)}
          type="button"
        />
      ) : null}
      {showPalette ? (
        <div className="absolute left-16 top-1/2 z-50 -translate-y-1/2">
          <PaletteOptions />
        </div>
      ) : null}
    </>
  );
}
