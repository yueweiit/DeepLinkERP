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
        state.epoch++;
        state.request = null;
        clearTimeout(state.timeout);
        restore(state);
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

    function requestView(control, state, context, term) {
        const request = {
            epoch: ++state.epoch, value: state.$input.val(), key: context.key,
            term, completed: false,
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
        const context = queryContext(control, state.kind, term);
        if (state.kind === "link" && !context.args) return;
        const receiver = requestView(control, state, context, term);
        return state.kind === "link"
            ? nativeSearch.call(receiver, {target: {value: term}})
            : nativeSearch.call(receiver, term);
    }

    function browse(control, state, nativeSearch) {
        if (!editable(control, state) || !state.$input.is(":focus")) return;
        const context = queryContext(control, state.kind, "");
        if (state.displayedKey && state.displayedKey !== context.key) {
            state.widget.list = [];
        }
        const request = state.request;
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
            if (request.completed) {
                state.widget.evaluate();
                state.widget.open();
            }
            return;
        }
        if (state.kind === "autocomplete" && !context.source) {
            state.displayedKey = context.key;
            state.widget.list = control.get_data();
            state.widget.evaluate();
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
        };
        states.set(control, state);
        // Run before Awesomplete's earlier input listener and Frappe's jQuery handler.
        state.input.addEventListener("input", () => invalidate(state), true);
        state.input.addEventListener("focus", () => {
            if (!editable(control, state) || !state.displayedKey) return;
            try {
                if (state.displayedKey !== queryContext(control, kind, "").key) {
                    invalidate(state);
                    state.widget.list = [];
                }
            } catch (_) {
                invalidate(state);
                state.widget.list = [];
            }
        }, true);
        state.input.addEventListener("keydown", event => {
            if (state.browse && ["ArrowDown", "ArrowUp"].includes(event.key)) {
                state.keyboardChoice = true;
            }
        }, true);
        state.$input.on("click.selection-dropdown", () => browse(control, state, nativeSearch));
        state.$input.on("blur.selection-dropdown awesomplete-close.selection-dropdown", () => invalidate(state));
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
