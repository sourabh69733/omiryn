import { useEffect } from "react";

const FOCUSABLE = 'button:not(:disabled), [href], input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

function focusables(root: Element) {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.getClientRects().length > 0);
}

function menuItems(menu: Element) {
  return [...menu.querySelectorAll<HTMLElement>('[role="menuitem"]:not(:disabled)')];
}

// Keyboard behavior for every menu and modal dialog in the app, so each component does not
// re-implement it:
// - a menu (role="menu") focuses its first item when it opens; arrow keys, Home and End move
//   between items; focus goes back to what opened it when it closes.
// - a modal dialog (role="dialog" with aria-modal="true") takes focus when it opens, keeps Tab
//   inside, and gives focus back when it closes. Dialogs that manage this themselves opt out
//   with data-focus-managed. Escape stays with each component, which knows how to close itself.
export function useKeyboardA11y() {
  useEffect(() => {
    if (typeof MutationObserver === "undefined") return;
    const openedFrom = new Map<Element, HTMLElement | null>();

    const onAdded = (el: Element) => {
      const isMenu = el.getAttribute("role") === "menu";
      const isModal = el.getAttribute("role") === "dialog" && el.getAttribute("aria-modal") === "true" && !el.hasAttribute("data-focus-managed");
      if (!isMenu && !isModal) return;
      const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      openedFrom.set(el, active);
      if (el.contains(document.activeElement)) return;
      const first = isMenu ? menuItems(el)[0] : el.querySelector<HTMLElement>("[data-autofocus]") ?? focusables(el)[0];
      first?.focus();
    };

    const onRemoved = (el: Element) => {
      if (!openedFrom.has(el)) return;
      const back = openedFrom.get(el);
      openedFrom.delete(el);
      // Only when focus was lost with the closed element; never steal it from where it moved.
      const lost = !document.activeElement || document.activeElement === document.body;
      if (lost && back && document.contains(back)) back.focus();
    };

    const observer = new MutationObserver((records) => {
      for (const record of records) {
        record.removedNodes.forEach((node) => {
          if (!(node instanceof Element)) return;
          [node, ...node.querySelectorAll('[role="menu"], [role="dialog"]')].forEach(onRemoved);
        });
        record.addedNodes.forEach((node) => {
          if (!(node instanceof Element)) return;
          [node, ...node.querySelectorAll('[role="menu"], [role="dialog"]')].forEach(onAdded);
        });
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    const onKeyDown = (event: KeyboardEvent) => {
      const active = document.activeElement;
      if (!(active instanceof HTMLElement)) return;
      const menu = active.closest('[role="menu"]');
      if (menu && ["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        const items = menuItems(menu);
        if (!items.length) return;
        event.preventDefault();
        const index = items.indexOf(active);
        const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items[next].focus();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = active.closest('[role="dialog"][aria-modal="true"]:not([data-focus-managed])');
      if (!dialog) return;
      const list = focusables(dialog);
      if (!list.length) return;
      const first = list[0];
      const last = list[list.length - 1];
      if (event.shiftKey && active === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && active === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);

    return () => {
      observer.disconnect();
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);
}
