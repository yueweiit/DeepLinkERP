  bindHorizontalScrollController({
    content,
    header = null,
    scrollbar,
    spacer,
    leftButton = null,
    rightButton = null,
    onInteraction = null,
    onRefresh = null,
  }) {
    if (!content || !scrollbar || !spacer) return () => {};
    let syncing = false;
    let frame = null;
    let programmaticContentLeft = null;
    let programmaticScrollbarLeft = null;
    const interact = () => {
      if (typeof onInteraction === "function") onInteraction();
    };
    const metrics = () => ({
      contentMax: Math.max(0, content.scrollWidth - content.clientWidth),
      scrollbarMax: Math.max(0, scrollbar.scrollWidth - scrollbar.clientWidth),
    });
    const setButtons = (maximum) => {
      if (leftButton) leftButton.disabled = maximum <= 1 || content.scrollLeft <= 1;
      if (rightButton) rightButton.disabled = maximum <= 1 || content.scrollLeft >= maximum - 1;
    };
    const syncFromContent = () => {
      const { contentMax, scrollbarMax } = metrics();
      const left = Math.min(contentMax, Math.max(0, content.scrollLeft));
      if (content.scrollLeft !== left) content.scrollLeft = left;
      if (header) header.scrollLeft = left;
      const scrollbarLeft = contentMax > 0 ? (left / contentMax) * scrollbarMax : 0;
      if (Math.abs(scrollbar.scrollLeft - scrollbarLeft) > 0.5) {
        programmaticScrollbarLeft = scrollbarLeft;
        scrollbar.scrollLeft = scrollbarLeft;
      }
      setButtons(contentMax);
    };
    const refresh = () => {
      if (frame !== null) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        spacer.style.width = `${Math.max(content.scrollWidth, scrollbar.clientWidth)}px`;
        scrollbar.classList.toggle("is-hidden", content.scrollWidth <= content.clientWidth + 1);
        syncFromContent();
        if (typeof onRefresh === "function") onRefresh();
      });
    };
    const onContentScroll = () => {
      if (syncing) return;
      if (programmaticContentLeft !== null) {
        const matched = Math.abs(content.scrollLeft - programmaticContentLeft) <= 0.5;
        programmaticContentLeft = null;
        if (matched) {
          if (header) header.scrollLeft = content.scrollLeft;
          setButtons(metrics().contentMax);
          return;
        }
      }
      syncing = true;
      interact();
      syncFromContent();
      syncing = false;
    };
    const onScrollbarScroll = () => {
      if (syncing) return;
      if (programmaticScrollbarLeft !== null) {
        const matched = Math.abs(scrollbar.scrollLeft - programmaticScrollbarLeft) <= 0.5;
        programmaticScrollbarLeft = null;
        if (matched) return;
      }
      syncing = true;
      interact();
      const { contentMax, scrollbarMax } = metrics();
      const nextLeft = scrollbarMax > 0 ? (scrollbar.scrollLeft / scrollbarMax) * contentMax : 0;
      programmaticContentLeft = nextLeft;
      content.scrollLeft = nextLeft;
      if (header) header.scrollLeft = nextLeft;
      setButtons(contentMax);
      syncing = false;
    };
    const move = (direction) => {
      interact();
      content.scrollBy({
        left: direction * Math.max(240, content.clientWidth * 0.65),
        behavior: "smooth",
      });
    };
    const moveLeft = () => move(-1);
    const moveRight = () => move(1);
    content.addEventListener("scroll", onContentScroll, { passive: true });
    scrollbar.addEventListener("scroll", onScrollbarScroll, { passive: true });
    leftButton?.addEventListener("click", moveLeft);
    rightButton?.addEventListener("click", moveRight);
    window.addEventListener("resize", refresh);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(refresh);
    observer?.observe(content);
    const table = content.querySelector("table");
    if (table) observer?.observe(table);
    refresh();
    return () => {
      content.removeEventListener("scroll", onContentScroll);
      scrollbar.removeEventListener("scroll", onScrollbarScroll);
      leftButton?.removeEventListener("click", moveLeft);
      rightButton?.removeEventListener("click", moveRight);
      window.removeEventListener("resize", refresh);
      observer?.disconnect();
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }
