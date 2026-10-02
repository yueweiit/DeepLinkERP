/* Browse native editable selectors without changing their displayed/model value.
 * Native queries, renderers, replacement, selection callbacks and validation remain
 * owned by Frappe. Each native search runs with a request-local display receiver. */
(() => {
    const frappe = window.frappe;
    if (!frappe || frappe._selection_dropdown_installed) return;
    frappe._selection_dropdown_installed = true;

    const states = new WeakMap();
    const patched = new WeakSet();
    const identities = new WeakMap();
    let identity = 0;

    function fingerprint(value, seen = new Set()) {
        if (typeof value === "function") {
            if (!identities.has(value)) identities.set(value, ++identity);
            return `function:${identities.get(value)}`;
        }
        if (!value || typeof value !== "object") return JSON.stringify(value);
        if (seen.has(value)) return "circular";
        seen.add(value);
        const result = Array.isArray(value)
            ? `[${value.map(item => fingerprint(item, seen)).join(",")}]`
            : `{${Object.keys(value).sort().map(key =>
                `${JSON.stringify(key)}:${fingerprint(value[key], seen)}`).join(",")}}`;
        seen.delete(value);
        return result;
    }

    function editable(control, state) {
        return states.get(control) === state && control.input === state.input &&
            control.awesomplete === state.widget && state.input.isConnected !== false &&
            !state.input.disabled && !state.input.readOnly &&
            !control.df?.read_only && !control.df?.disabled &&
            (!control.disp_status || control.disp_status === "Write");
    }

    function restore(state) {
        state.widget.filter = state.filter;
        state.widget.autoFirst = state.autoFirst;
        state.widget.tabSelect = state.tabSelect;
        state.browse = false;
        state.keyboardChoice = false;
    }

    function invalidate(state) {
        state.debouncedInput?.cancel();
        state.epoch++;
        state.request = null;
        clearTimeout(state.timeout);
        restore(state);
    }

    function storedValue(control) {
        return control.get_model_value?.() ?? control.value ?? control.last_value;
    }

    function storedTokens(value) {
        return String(value ?? "").split(",").map(value => value.trim()).filter(Boolean);
    }

    function autocompleteQuery(control) {
        const source = control.get_query || control.df.get_query;
        // Frappe deliberately calls function queries as raw functions, not methods.
        const query = typeof source === "function"
            ? source((control.frm && control.frm.doc) || control.doc, control.doctype, control.docname)
            : source;
        return {source, query};
    }

    function queryContext(control, kind, term) {
        if (kind === "link") {
            const args = control.get_search_args(term);
            return {args, key: fingerprint(args)};
        }
        const result = autocompleteQuery(control);
        return {...result, key: fingerprint({
            ...result, doc: (control.frm && control.frm.doc) || control.doc,
            doctype: control.doctype, docname: control.docname,
        })};
    }

    function clearObsoleteDisplay(control, state, term) {
        if (!state.displayedKey) return;
        try {
            if (state.displayedKey === queryContext(control, state.kind, term).key) return;
        } catch (_) {
            // Missing native dependency: discard options that no longer have a context.
        }
        state.displayedKey = null;
        state.widget.list = [];
    }

    function requestView(control, state, context, term) {
        const request = {
            epoch: ++state.epoch, value: state.$input.val(), key: context.key,
            term, completed: false, browse: state.browse,
        };
        state.request = request;
        const current = () => {
            if (!editable(control, state) || state.request !== request ||
                state.epoch !== request.epoch || !state.$input.is(":focus") ||
                state.$input.val() !== request.value) return false;
            try {
                return queryContext(control, state.kind, term).key === request.key;
            } catch (_) {
                // A changed/missing Dynamic Link target can make its native query invalid.
                return false;
            }
        };
        request.current = current;
        // Native Link caches only doctype + term; add the effective query context.
        if (!state.caches.has(context.key)) state.caches.set(context.key, {});
        const inputView = new Proxy(state.$input, {
            get(target, name) {
                if (name === "cache") return state.caches.get(context.key);
                if (name === "is") return selector => selector === ":focus"
                    ? current() : target.is(selector);
                const value = Reflect.get(target, name);
                return typeof value === "function" ? value.bind(target) : value;
            },
        });
        const widgetView = new Proxy(state.widget, {
            get(target, name) {
                const value = Reflect.get(target, name);
                return typeof value === "function" ? value.bind(target) : value;
            },
            set(target, name, value) {
                if (name === "list") {
                    // This check also runs after native get_filter_description awaits.
                    if (!current()) return true;
                    request.completed = true;
                    state.displayedKey = context.key;
                    clearTimeout(state.timeout);
                }
                return Reflect.set(target, name, value);
            },
        });
        // Native searches do not return their frappe.call request or expose errors.
        // Release a failed pending browse for the user's next click; never auto-retry.
        clearTimeout(state.timeout);
        state.timeout = setTimeout(() => {
            if (state.browse && state.request === request && !request.completed) invalidate(state);
        }, 10000);
        return new Proxy(control, {
            get(target, name) {
                if (name === "$input") return inputView;
                if (name === "awesomplete") return widgetView;
                if (name === "get_search_args") return () => context.args;
                if (name === "get_query" && state.kind === "autocomplete") {
                    return typeof context.source === "function" ? () => context.query : context.query;
                }
                if (name === "set_data") return data => {
                    if (!current()) return;
                    request.completed = true;
                    state.displayedKey = context.key;
                    clearTimeout(state.timeout);
                    if (request.browse) {
                        // Browsing must preserve the current label-to-value mapping.
                        // The native change/validation callback receives these only
                        // after an actual Awesomplete selection completes.
                        state.browseCandidates = target.parse_options(data);
                        widgetView.list = state.browseCandidates;
                        return;
                    }
                    return target.set_data(data);
                };
                if (name === "toggle_href") return (...args) => {
                    if (current()) return target.toggle_href(...args);
                };
                const value = Reflect.get(target, name);
                return typeof value === "function" ? value.bind(target) : value;
            },
        });
    }

    function search(control, state, term, nativeSearch) {
        if (!editable(control, state)) return;
        clearObsoleteDisplay(control, state, term);
        const context = queryContext(control, state.kind, term);
        if (state.kind === "link" && !context.args) return;
        const receiver = requestView(control, state, context, term);
        state.inNativeSearch = true;
        try {
            return state.kind === "link"
                ? nativeSearch.call(receiver, {target: {value: term}})
                : nativeSearch.call(receiver, term);
        } finally {
            state.inNativeSearch = false;
        }
    }

    function browse(control, state, nativeSearch) {
        if (!editable(control, state) || !state.$input.is(":focus")) return;
        state.debouncedInput?.cancel();
        if (state.kind === "autocomplete") {
            const source = storedValue(control);
            const values = control.df.fieldtype === "MultiSelect" ? control.get_values() : null;
            // Native option mapping can silently drop an unknown search token.
            // Require every raw token to be represented before accepting that mapping.
            const unchanged = control.get_input_value() === source ||
                (values && values.length === state.$input.val().replace(/,\s*$/, "").split(",").length &&
                    fingerprint(values) === fingerprint(storedTokens(source)));
            state.cancelSnapshot = unchanged
                ? {input: state.$input.val(), source} : null;
        }
        const context = queryContext(control, state.kind, "");
        clearObsoleteDisplay(control, state, "");
        const request = state.request;
        state.pendingSelection = null;
        state.browse = true;
        state.keyboardChoice = false;
        state.widget.autoFirst = false;
        state.widget.tabSelect = false;
        state.widget.filter = function (item) {
            const allowed = state.filter.call(this, item, "");
            if (!allowed || control.df.fieldtype !== "MultiSelect") return allowed;
            const values = control.get_values() || [];
            return !values.includes(item.value) && !values.includes(item.label);
        };
        // Focus on an empty Link may already have launched exactly this query.
        if (request && request.term === "" && request.key === context.key && request.current()) {
            request.browse = true;
            if (request.completed) {
                state.widget.evaluate();
                state.widget.open();
            }
            return;
        }
        if (state.kind === "autocomplete" && !context.source) {
            const receiver = requestView(control, state, context, "");
            receiver.set_data(control.get_data.call(receiver));
            return;
        }
        search(control, state, "", nativeSearch);
    }

    function bind(control, kind, nativeSearch) {
        if (!control.input || !control.$input || !control.awesomplete) return;
        const previous = states.get(control);
        if (previous?.input === control.input && previous.widget === control.awesomplete) return;
        if (previous) invalidate(previous);
        const state = {
            input: control.input, $input: control.$input, widget: control.awesomplete,
            kind, epoch: 0, caches: new Map(), filter: control.awesomplete.filter,
            autoFirst: control.awesomplete.autoFirst, tabSelect: control.awesomplete.tabSelect,
            debouncedInput: control._debounced_input_handler,
        };
        states.set(control, state);
        const close = state.widget.close;
        state.widget.close = function (...args) {
            // Native close emits no event when already hidden. A queued Link
            // debounce must still be canceled when the caller closes the selector.
            // An empty native cache can close the widget while on_input is
            // still starting its refresh. Preserve that new request.
            if (!state.inNativeSearch) invalidate(state);
            return close.apply(this, args);
        };
        // Run before Awesomplete's earlier input listener and Frappe's jQuery handler.
        state.input.addEventListener("input", () => {
            state.cancelSnapshot = null;
            state.pendingSelection = null;
            state.browseCandidates = null;
            invalidate(state);
            clearObsoleteDisplay(control, state, state.input.value);
        }, true);
        state.input.addEventListener("focus", () => {
            if (!editable(control, state) || !state.displayedKey) return;
            clearObsoleteDisplay(control, state, "");
        }, true);
        if (kind === "autocomplete") {
            state.input.addEventListener("blur", () => {
                const snapshot = state.cancelSnapshot;
                state.cancelSnapshot = null;
                // Standalone Data remembers the previous value in last_value.
                // Skip only the redundant validation of unchanged stored input;
                // typed search tokens and changed sources retain native validation.
                if (snapshot && editable(control, state) &&
                    state.$input.val() === snapshot.input && storedValue(control) === snapshot.source) {
                    control.last_value = control.get_input_value();
                }
            }, true);
            state.input.addEventListener("awesomplete-select", event => {
                const value = event.text?.value;
                state.pendingSelection = state.browse && state.request?.current() &&
                    state.browseCandidates?.some(item => item.value === value)
                    ? {value, data: state.browseCandidates, key: state.request.key,
                        term: state.request.term,
                        stored: control.df.fieldtype === "MultiSelect"
                            ? storedTokens(storedValue(control)) : null} : null;
            }, true);
            state.input.addEventListener("awesomplete-selectcomplete", event => {
                state.cancelSnapshot = null;
                const selected = state.pendingSelection;
                state.pendingSelection = null;
                if (!selected || event.text?.value !== selected.value || !editable(control, state)) return;
                if (queryContext(control, kind, selected.term).key !== selected.key) return;
                if (control.df.fieldtype === "MultiSelect") {
                    // Native replace treats a saved final token as the search
                    // token. Only retain validated model values, never a typed
                    // query tail that has not been selected.
                    const tokens = selected.stored.map(value => control.df.ignore_validation
                        ? control._data?.find(item => item.value === value)?.label || value : value);
                    const choice = control.df.ignore_validation
                        ? String(event.text.label || selected.value) : selected.value;
                    if (!selected.stored.includes(selected.value)) tokens.push(choice);
                    // Native validation splits commas without trimming each token.
                    const separator = control.df.ignore_validation ? ", " : ",";
                    state.$input.val(tokens.join(separator) + ", ");
                }
                const merged = new Map((control._data || [])
                    .filter(item => selected.stored?.includes(item.value))
                    .map(item => [item.value, item]));
                selected.data.forEach(item => merged.set(item.value, item));
                // A remote page may omit already stored selections. Preserve
                // only those model values in the native validation backing list.
                selected.stored?.forEach(value => {
                    if (!merged.has(value)) merged.set(value, {label: value, value});
                });
                control._data = [...merged.values()];
                // Native validation includes existing MultiSelect values. Assign
                // the parsed backing list directly so a selection never reopens it.
                state.widget._list = control._data;
            }, true);
        }
        state.input.addEventListener("keydown", event => {
            if (state.browse && ["ArrowDown", "ArrowUp"].includes(event.key)) {
                state.keyboardChoice = true;
            }
        }, true);
        state.$input.on("click.selection-dropdown", () => browse(control, state, nativeSearch));
        state.$input.on("blur.selection-dropdown", () => invalidate(state));
        state.$input.on("awesomplete-close.selection-dropdown", () => {
            if (!state.inNativeSearch) invalidate(state);
        });
    }

    function patch(Control, kind) {
        if (!Control || patched.has(Control)) return;
        patched.add(Control);
        const prototype = Control.prototype;
        const makeInput = prototype.make_input;
        const method = kind === "link" ? "on_input" : "execute_query_if_exists";
        const nativeSearch = prototype[method];
        prototype.make_input = function (...args) {
            const result = makeInput.apply(this, args);
            bind(this, kind, nativeSearch);
            return result;
        };
        prototype[method] = function (eventOrTerm) {
            const state = states.get(this);
            if (!state) return nativeSearch.call(this, eventOrTerm);
            if (kind === "link" && eventOrTerm && eventOrTerm.target !== state.input) return;
            const term = kind === "link"
                ? (eventOrTerm ? eventOrTerm.target.value : this.$input.val()) : eventOrTerm;
            return search(this, state, term, nativeSearch);
        };
        if (kind === "link") {
            const matches = prototype.input_matches_item;
            prototype.input_matches_item = function (...args) {
                const state = states.get(this);
                if (state?.browse && state.keyboardChoice && state.request?.current()) return true;
                return matches.apply(this, args);
            };
        }
    }

    function install() {
        const form = frappe.ui?.form;
        if (!form) return;
        for (const [name, kind] of [["ControlLink", "link"], ["ControlAutocomplete", "autocomplete"]]) {
            if (form[name]) {
                patch(form[name], kind);
            } else if (!Object.getOwnPropertyDescriptor(form, name)) {
                // app_include_js can run before Desk's control classes are assigned.
                // Observe that one assignment, then restore a normal property.
                Object.defineProperty(form, name, {
                    configurable: true,
                    get: () => undefined,
                    set(Control) {
                        Object.defineProperty(form, name, {value: Control, writable: true,
                            enumerable: true, configurable: true});
                        patch(Control, kind);
                    },
                });
            }
        }
    }
    frappe.provide("frappe.ui.form");
    install();
    document.addEventListener("DOMContentLoaded", install, {once: true});
    $(document).on("app_ready.selection-dropdown", install);
})();
