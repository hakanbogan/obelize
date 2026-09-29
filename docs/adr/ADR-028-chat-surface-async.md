# ADR-028: Chat surface and async

## Status

Accepted.

## Decision

### D1. A binding group is the transitive closure of what its calls produce

A call whose method is in `method_returns` pulls the bindings holding its
result into the constructor's group, because a chat stands or falls with its
model: rewriting only one of `start_chat` and `send_message` sends one SDK's
object the other's call. The walk is breadth-first, so a producing call is
planned before the calls on what it produced (D3). Only a `call` to
`ctor_symbol` starts a group, so a binding in a closure never roots one.

### D2. The pack says where a new call is rooted, and one field decides three things

`MethodRewrite.root` is `client` or `receiver`, and decides where the call is
made, whether `model=` is prepended and whether the configuration is restated:
nothing on the client holds the model or its configuration, while a chat was
given both when it was created. `receiver` keeps the author's receiver node
(`self.chat`, `chat`). The schema requires a service in `new_call` under
`client` and a bare method under `receiver`.

### D3. A chat's configuration is the chat's, and the new SDK replaces it

The legacy chat merged the model's configuration with the call's key by key;
the new `Chat.send_message` uses `config if config else self._config`. So each
binding carries the configuration its producing call emitted. A
receiver-rooted call that states none emits no `config=`; one that states any
emits the object's whole configuration with the call's keys written over it,
or the other keys would silently go. A client-rooted call always carries the
merge.

### D4. The safety table is read from two forms, against two tables

The legacy lookup took a string, lower-cased into a closed table, or an enum
member, and the two sets differ (`HarmBlockThreshold.OFF` is a member; `"off"`
raised `KeyError`), so the pack carries string maps and member lists apart under
`safety`. A member is recognised by its class (`legacy_category_class`,
`legacy_threshold_class`), which is not in `match.symbols`: the rule reads only
the member name, so a finding would be a row no rule claims. Accepted shapes: a
category-to-threshold mapping, or a sequence of one-row mappings keyed by
`legacy_category_key` and `legacy_threshold_key`, declared apart from the new
class's keywords. A name outside the tables, and any other shape, is
`safety_settings_not_static`, because the new enums fabricate an unknown member
with only a warning (C-02).

### D5. Two safety tables merge by category, not wholesale

A call's safety table overrides the constructor's per category, in the
constructor's position, and a category only the call names is appended, as
the legacy `merged_ss.update(...)` did. Replacing the whole table would drop a
category the author set.

### D6. The rebuilt argument is emitted after the carried ones

The configuration object's fields are the constructor parameters carried
verbatim, then the author's configuration keys, then the safety table, which
is rebuilt as `types.SafetySetting(...)` calls and so goes below the author's
own spellings. `layout.sequence` lays the list out by the call's clauses: one
element per line when the source was multi-line, when an element is, or when
the line would be too wide.

### D7. A history is reshaped only where the shape is literal, and a part only where it is certainly a string

A history is a list of mappings, each with exactly the role and parts keys as
string literals, a role the pack lists, and a list of parts. A string literal or
f-string part is wrapped, and a part already in the new one-key mapping passes;
anything else is `history_parts_shape_incompatible`, because a name may hold a
`types.Part` and wrapping it fails at the first message. A list of turns in a
client call's `contents_kwarg` is reshaped the same way; a single turn, a name
filled with one, or a turn in a chat's message is refused under the same code.
`history_parts_rewritten` warns only when something was reshaped.

### D8. A keyword whose default flipped is refused per method as well as per constructor

Automatic function calling is off by default in the legacy SDK and on in the
new one, so neither moving nor dropping the keyword keeps its behaviour.
`ctor_afc_kwargs` refuses `tools=` and `tool_config=` on the constructor, and
`MethodRewrite.afc_kwargs` refuses the same fact per method
(`start_chat(enable_automatic_function_calling=)`), both as
`afc_semantics_differ`.

### D9. `send_message_async` has no rewrite, and that is a decision rather than a gap

The async chat hangs off `client.aio.chats`, a different object from
`client.chats`, so a chat used both ways cannot be written one call at a time.
The method stays declared and unmapped (ADR-027 D1), and `tests/oracle/`
asserts that the rewritten methods are the declared ones minus this one.

### D10. The `await` is preserved, and a source that never had one is refused

`MethodRewrite.coroutine` marks a coroutine function on both sides. The rule
replaces the call and never the expression around it, so an `await` carries
over; the streaming branch warns `async_stream_await_preserved`. A `for` or
`async for` directly over such a streaming call without `await` is
`async_stream_await_missing`: it already raises `TypeError` (ADR-010 F-8). The
streaming method returns a generator with no `resolve()` or `text`, so a stream
is written only as a `for` iterable or bound to one name used only as one;
otherwise `response_shape_changed`.

### D11. A method with no rewrite still hands its receiver to the group

The closure follows `method_returns` whether or not the producing method has a
rewrite, so calls on a chat an unmapped method produced are refused with the
group, not orphaned as `receiver_unresolved`: one defect, one name.

### D12. A group the scan refused is refused under the scan's own code

Before asking anything about a group's shape, the rule repeats the code the scan
wrote on any of its bindings, so one defect keeps one name. Under the default
`atomic` import policy no such group forms; under `dual` a withheld binding can
sit in an eligible closure, which would otherwise be written with a hole.
`tests/unit/` reaches it by passing the policy.

### D13. `chat_config_class` is removed, because no rule could reach it

It named the class a chat's `config=` carries, but a call's configuration
keyword is declared on its `MethodRewrite` and no rewrite could ask for a class
declared on the rule. The rule's `config_class` serves every call; a pack that
needs two classes adds a per-rewrite override then.

### D14. A rewritten call names its arguments, even where the new signature would take them positionally

`chat.send_message(text)` becomes `chat.send_message(message=text)` although
the new method takes `message` positionally, because the rename `content` to
`message` (C-17) is a `TypeError` if missed, and a diff that shows the keyword
shows it was not.

## Consequences

- `tests/fixtures/scan/chat_async_self/assistant.after.py` is produced by rule,
  byte for byte, with its three graded warnings.
- In the bundled pack `receiver_method_unmapped` fires only through
  `send_message_async`.
- Automatic function calling gets no destination: what it should be in a file
  that never mentioned it is the user's decision.
- Open: `count_tokens` refuses `system_instruction`, a field
  `types.CountTokensConfig` has, so the pack's `generate_content.before.py`
  stays refused; `(await f(x)).attr` wraps at the call where `ruff format` would
  break the outer parenthesis, and how often that shape occurs is unmeasured.
