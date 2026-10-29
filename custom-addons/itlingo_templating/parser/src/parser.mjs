// DSL -> JSON AST CLI.
//
// Usage: node parser.mjs <grammarPath> <sourcePath> [label] [validationMode] [servicesModulePath]
// Builds Langium services from the grammar text at runtime (createServicesForGrammar)
// and prints {success, ast, error, diagnostics, ast_summary} as JSON on stdout.
//
// Langium stays external so this parser and author-supplied services modules can
// resolve the same runtime instance from parser/node_modules.

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { EmptyFileSystem, URI } from 'langium';
import {
  collectAst,
  collectTypeHierarchy,
  createLangiumGrammarServices,
  createServicesForGrammar,
  mergeTypesAndInterfaces,
} from 'langium/grammar';

// Mirrors itlingo_dsl/services/grammar_flattener.py flatten_grammar: a file
// already inlined is skipped, and only a file still on the recursion stack is a
// genuine cycle. One shared `seen` set conflated the two, so a diamond — the ten
// files of languium-dsls/current/RSL-2.9/grammar that each import './Terminals' —
// was rejected as circular and the grammar never loaded.
function loadGrammar(grammarPath, done = new Set(), inProgress = []) {
  const absolutePath = resolve(grammarPath);
  if (done.has(absolutePath)) {
    return '';
  }
  if (inProgress.includes(absolutePath)) {
    const cycle = [...inProgress.slice(inProgress.indexOf(absolutePath)), absolutePath];
    throw new Error(`Circular grammar import: ${cycle.join(' -> ')}`);
  }
  inProgress.push(absolutePath);

  const baseDir = dirname(absolutePath);
  const grammar = readFileSync(absolutePath, 'utf-8');
  const imports = [];
  const grammarWithoutImports = grammar.replace(
    /^(\s*)import\s+['"]([^'"]+)['"]\s*;?\s*$/gm,
    (_match, _indent, importedPath) => {
      const fileName = importedPath.endsWith('.langium')
        ? importedPath
        : `${importedPath}.langium`;
      imports.push(loadGrammar(resolve(baseDir, fileName), done, inProgress));
      return '';
    },
  );
  inProgress.pop();
  done.add(absolutePath);
  return [grammarWithoutImports, ...imports].join('\n');
}

async function parseGrammar(grammar) {
  const grammarServices = createLangiumGrammarServices(EmptyFileSystem).grammar;
  const document = grammarServices.shared.workspace.LangiumDocumentFactory.fromString(
    grammar,
    URI.parse('memory:/grammar.langium'),
  );
  await grammarServices.shared.workspace.DocumentBuilder.build(
    [document],
    { validation: false },
  );
  return {
    grammarNode: document.parseResult.value,
    grammarServices,
  };
}

function repairNestedUnionReflection(parsedGrammar, reflection) {
  const hierarchy = collectTypeHierarchy(
    mergeTypesAndInterfaces(collectAst(parsedGrammar.grammarNode, {
      services: parsedGrammar.grammarServices,
    })),
  );
  for (const name of hierarchy.superTypes.keys()) {
    if (!reflection.types[name]) {
      reflection.types[name] = {
        name,
        properties: {},
        superTypes: [...hierarchy.superTypes.get(name)],
      };
    }
  }

  reflection.subtypes = {};
  reflection.allSubtypes = {};
}

function serializeValue(value, seen) {
  // Langium cross-reference: tag with {$ref: targetName}; the target is never
  // inlined (avoids cycles/duplication). Python resolves it against by_id.
  if (value && typeof value === 'object' && typeof value.$refText === 'string') {
    return { $ref: value.$refText };
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => serializeValue(item, seen))
      .filter((item) => item !== undefined);
  }
  if (value && typeof value === 'object') {
    return serializeAstNode(value, seen);
  }
  return value;
}

function serializeAstNode(node, seen = new WeakSet()) {
  if (!node || typeof node !== 'object') {
    return node;
  }
  if (seen.has(node)) {
    return undefined;
  }
  seen.add(node);

  const output = {};
  for (const [key, value] of Object.entries(node)) {
    if (key === '$container' || key === '$document' || key === '$cstNode' || key === '$refNode') {
      continue;
    }
    if (key === '$type') {
      output[key] = value;
      continue;
    }
    if (key.startsWith('$')) {
      continue;
    }
    output[key] = serializeValue(value, seen);
  }
  return output;
}

function countNodes(node) {
  if (!node || typeof node !== 'object') {
    return 0;
  }
  let count = 1;
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        count += countNodes(item);
      }
    } else if (value && typeof value === 'object') {
      count += countNodes(value);
    }
  }
  return count;
}

function collectShape(node, shape = { types: new Set(), namedTypes: new Set() }) {
  if (!node || typeof node !== 'object') {
    return shape;
  }
  if (typeof node.$type === 'string') {
    shape.types.add(node.$type);
    if (typeof node.name === 'string' && node.name) {
      shape.namedTypes.add(node.$type);
    }
  }
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) {
      value.forEach((item) => collectShape(item, shape));
    } else if (value && typeof value === 'object') {
      collectShape(value, shape);
    }
  }
  return shape;
}

async function withStdoutRedirect(callback) {
  const stdoutWrite = process.stdout.write;
  process.stdout.write = (...args) => process.stderr.write(...args);
  try {
    return await callback();
  } finally {
    process.stdout.write = stdoutWrite;
  }
}

function emit(result) {
  process.stdout.write(JSON.stringify(result));
}

async function loadServicesModule(servicesModulePath) {
  const imported = await import(pathToFileURL(resolve(servicesModulePath)).href);
  const module = typeof imported.default === 'function'
    ? imported.default()
    : imported.default;
  if (
    typeof module !== 'object'
    || module === null
    || Array.isArray(module)
    || typeof module.then === 'function'
  ) {
    throw new TypeError(
      'The services module default export must be a synchronous Langium module object or factory',
    );
  }
  return module;
}

async function main() {
  const [
    grammarPath,
    sourcePath,
    labelArg,
    validationModeArg,
    servicesModulePath,
  ] = process.argv.slice(2);
  const label = labelArg || 'DSL specification';
  const validationMode = validationModeArg || 'all';
  if (!grammarPath || !sourcePath) {
    emit({
      success: false,
      error: 'Usage: parser.mjs <grammarPath> <sourcePath> [label] [validationMode] [servicesModulePath]',
      diagnostics: [],
    });
    process.exit(2);
    return;
  }

  let grammar;
  let dslText;
  try {
    grammar = loadGrammar(grammarPath);
    dslText = readFileSync(sourcePath, 'utf-8');
  } catch (err) {
    emit({ success: false, error: `Cannot read input files: ${String(err)}`, diagnostics: [] });
    process.exit(1);
    return;
  }

  if (!dslText.trim()) {
    emit({ success: false, error: `Empty ${label}`, diagnostics: [] });
    process.exit(1);
    return;
  }

  let result;
  let exitCode = 0;
  try {
    result = await withStdoutRedirect(async () => {
      const parsedGrammar = await parseGrammar(grammar);
      const module = servicesModulePath
        ? await loadServicesModule(servicesModulePath)
        : undefined;
      const services = await createServicesForGrammar({
        grammar: parsedGrammar.grammarNode,
        grammarServices: parsedGrammar.grammarServices,
        module,
      });
      repairNestedUnionReflection(parsedGrammar, services.shared.AstReflection);
      const fileExtension = String(services.LanguageMetaData?.fileExtensions?.[0] || 'dsl').replace(/^\./, '');
      const factory = services.shared.workspace.LangiumDocumentFactory;
      const document = factory.fromString(dslText, URI.parse(`memory:///input.${fileExtension}`));

      const validateSemantics = validationMode !== 'syntax';
      await services.shared.workspace.DocumentBuilder.build([document], { validation: validateSemantics });

      const diagnostics = validateSemantics ? (document.diagnostics || []).map((d) => ({
        severity: d.severity,
        message: d.message,
        line: d.range?.start?.line ?? null,
        column: d.range?.start?.character ?? null,
      })) : [];

      // severity 1 == Error in the LSP diagnostic scale.
      const parserErrors = (document.parseResult?.parserErrors || []).map((e) => ({
        severity: 1,
        message: e.message,
        line: e.token?.startLine ?? null,
        column: e.token?.startColumn ?? null,
      }));
      const lexerErrors = (document.parseResult?.lexerErrors || []).map((e) => ({
        severity: 1,
        message: e.message,
        line: e.line ?? null,
        column: e.column ?? null,
      }));

      const allDiagnostics = [...parserErrors, ...lexerErrors, ...diagnostics];
      const hasError = parserErrors.length > 0 || lexerErrors.length > 0
        || allDiagnostics.some((d) => d.severity === 1);

      if (hasError) {
        exitCode = 1;
        return { success: false, error: `${label} has errors`, diagnostics: allDiagnostics };
      }

      const ast = serializeAstNode(document.parseResult.value);
      const shape = collectShape(ast);
      return {
        success: true,
        ast,
        diagnostics: allDiagnostics,
        ast_summary: {
          node_count: countNodes(ast),
          root_type: String(document.parseResult.value?.$type || 'Model'),
        },
        grammar_shape: {
          entry_type: String(document.parseResult.value?.$type || 'Model'),
          observed_types: [...shape.types].sort(),
          named_types: [...shape.namedTypes].sort(),
        },
      };
    });
  } catch (err) {
    result = { success: false, error: String(err?.stack || err), diagnostics: [] };
    exitCode = 1;
  }
  emit(result);
  if (exitCode) {
    process.exit(exitCode);
  }
}

main();
