grammar NestedUnion

entry Model:
    elements+=(Target | Other | Direct | Use)*;

Use:
    'use' target=[Outer:ID];

Target:
    'target' name=ID;

Other:
    'other' name=ID;

Direct:
    'direct' name=ID;

type Outer = Middle | Direct;
type Middle = Target | Other;

terminal ID: /[a-zA-Z_][a-zA-Z0-9_]*/;
hidden terminal WS: /\s+/;
