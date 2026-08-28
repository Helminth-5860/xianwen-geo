import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const frontendRoot = path.resolve(import.meta.dirname, "..");
const scanRoots = [
  path.join(frontendRoot, "app"),
  path.join(frontendRoot, "components"),
  path.join(frontendRoot, "lib"),
];
const ignoredSegments = new Set(["admin", "node_modules", ".next", "tests", "__tests__"]);

const visibleAttributeNames = new Set([
  "alt",
  "aria-label",
  "cancelText",
  "description",
  "emptyText",
  "help",
  "label",
  "message",
  "okText",
  "placeholder",
  "subTitle",
  "title",
  "tooltip",
]);

const visiblePropertyNames = new Set([
  "cancelText",
  "description",
  "emptyText",
  "help",
  "label",
  "message",
  "okText",
  "placeholder",
  "subTitle",
  "title",
  "tooltip",
]);

const visibleSetterNames =
  /^(set|show|open|push|add)(Error|Message|Notice|Alert|Toast|Warning|Success)$/;

const forbiddenPatterns = [
  {
    pattern:
      /\b(provider|runtime|adapter|payload|request|response|endpoint|worker|queue|job id|task id|request id|correlation id|token usage|retry|timeout|fallback|degraded|mock|staging|production|environment|api|api credential|api key|https?|json|schema version|config|debug|log|exception|traceback|cache|database|redis|celery|docker|ssr|csr|hydration|component|props|state|hook|client boundary|server component|no data|loading)\b/i,
    reason: "英文开发、接口或运维术语",
  },
  {
    pattern:
      /(接口|后端|运维|开发环境|生产环境|测试中|内部沟通|临时方案|后续优化|待开发|暂未接入|先占位|等后端|以后补|第一阶段|第二阶段|技术债|兼容旧接口|降级处理|任务编号|请求编号|原始高熵令牌|冻结快照)/,
    reason: "面向用户暴露了内部实现或内部沟通文案",
  },
  {
    pattern: /\b(TODO|MVP|V\d+)\b/i,
    reason: "面向用户暴露了内部版本或开发阶段",
  },
  {
    pattern: /\b(?:QUEUED|RUNNING|SUCCEEDED|FAILED|CANCELLED|PENDING|ACTIVE|INACTIVE)\b/,
    reason: "面向用户暴露了英文内部状态",
  },
  {
    pattern: /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b/,
    reason: "面向用户暴露了英文错误码或内部标识",
  },
  {
    pattern: /(?:生成|检测|导出|处理|蒸馏|正文|大纲)任务/,
    reason: "使用了面向系统实现的任务术语",
  },
];

const allowedProductTerms = [
  "AI",
  "GEO",
  "SEO",
  "PDF",
  "PNG",
  "JPEG",
  "WEBP",
  "GB",
  "KB",
  "MB",
  "DeepSeek",
  "Kimi",
  "GLM",
  "Word",
  "Excel",
];

function collectTsxFiles(directory, result = []) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.name.startsWith(".") || ignoredSegments.has(entry.name)) continue;
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      collectTsxFiles(entryPath, result);
    } else if (
      entry.isFile() &&
      (entry.name.endsWith(".tsx") || entry.name.endsWith(".ts")) &&
      !entry.name.endsWith(".test.tsx") &&
      !entry.name.endsWith(".test.ts") &&
      !entry.name.endsWith(".d.ts")
    ) {
      result.push(entryPath);
    }
  }
  return result;
}

function literalText(node) {
  if (ts.isStringLiteralLike(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
    return node.text;
  }
  return undefined;
}

function propertyName(node) {
  if (ts.isIdentifier(node) || ts.isStringLiteralLike(node)) return node.text;
  return undefined;
}

function lineAndColumn(sourceFile, node) {
  const location = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
  return `${location.line + 1}:${location.character + 1}`;
}

function checkVisibleText(sourceFile, node, value, findings) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return;

  for (const { pattern, reason } of forbiddenPatterns) {
    if (!pattern.test(normalized)) continue;
    findings.push({
      file: sourceFile.fileName,
      location: lineAndColumn(sourceFile, node),
      reason,
      value: normalized.length > 100 ? `${normalized.slice(0, 97)}...` : normalized,
    });
    break;
  }

  if (
    findings.at(-1)?.file === sourceFile.fileName &&
    findings.at(-1)?.location === lineAndColumn(sourceFile, node)
  ) {
    return;
  }

  let remaining = normalized.replace(/&[a-z]+;/gi, "");
  for (const term of allowedProductTerms) {
    remaining = remaining.replaceAll(new RegExp(`\\b${term}\\b`, "gi"), "");
  }
  if (/[A-Za-z]{2,}/.test(remaining)) {
    findings.push({
      file: sourceFile.fileName,
      location: lineAndColumn(sourceFile, node),
      reason: "包含未列入产品白名单的英文文案",
      value: normalized.length > 100 ? `${normalized.slice(0, 97)}...` : normalized,
    });
  }
}

function auditFile(file, findings) {
  const source = fs.readFileSync(file, "utf8");
  const sourceFile = ts.createSourceFile(
    file,
    source,
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );

  function visit(node) {
    if (ts.isJsxText(node)) {
      checkVisibleText(sourceFile, node, node.text, findings);
    }

    if (ts.isJsxAttribute(node) && visibleAttributeNames.has(node.name.text) && node.initializer) {
      if (ts.isStringLiteral(node.initializer)) {
        checkVisibleText(sourceFile, node.initializer, node.initializer.text, findings);
      } else if (ts.isJsxExpression(node.initializer) && node.initializer.expression) {
        const value = literalText(node.initializer.expression);
        if (value !== undefined)
          checkVisibleText(sourceFile, node.initializer.expression, value, findings);
      }
    }

    if (ts.isPropertyAssignment(node) && visiblePropertyNames.has(propertyName(node.name) ?? "")) {
      const value = literalText(node.initializer);
      if (value !== undefined) checkVisibleText(sourceFile, node.initializer, value, findings);
    }

    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      visibleSetterNames.test(node.expression.text)
    ) {
      const firstArgument = node.arguments[0];
      if (firstArgument) {
        const value = literalText(firstArgument);
        if (value !== undefined) checkVisibleText(sourceFile, firstArgument, value, findings);
      }
    }

    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      /(?:labels?|messages?|presentation|copy|texts?|titles?|reasons?)$/i.test(node.name.text) &&
      node.initializer
    ) {
      const auditValueTree = (valueNode, depth = 0) => {
        const value = literalText(valueNode);
        if (value !== undefined) {
          checkVisibleText(sourceFile, valueNode, value, findings);
          return;
        }
        if (ts.isPropertyAssignment(valueNode)) {
          const initializerValue = literalText(valueNode.initializer);
          const name = propertyName(valueNode.name) ?? "";
          if (initializerValue !== undefined) {
            if (depth === 0 || visiblePropertyNames.has(name)) {
              checkVisibleText(sourceFile, valueNode.initializer, initializerValue, findings);
            }
          } else {
            auditValueTree(valueNode.initializer, depth + 1);
          }
          return;
        }
        if (ts.isObjectLiteralExpression(valueNode)) {
          for (const property of valueNode.properties) auditValueTree(property, depth);
          return;
        }
        if (ts.isArrayLiteralExpression(valueNode)) {
          for (const element of valueNode.elements) auditValueTree(element, depth);
          return;
        }
        if (ts.isCallExpression(valueNode)) {
          for (const argument of valueNode.arguments) auditValueTree(argument, depth);
        }
      };
      auditValueTree(node.initializer);
    }

    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
}

const findings = [];
const files = scanRoots.flatMap((root) => collectTsxFiles(root));
for (const file of files) auditFile(file, findings);

const uniqueFindings = [
  ...new Map(
    findings.map((finding) => [
      `${finding.file}:${finding.location}:${finding.reason}:${finding.value}`,
      finding,
    ]),
  ).values(),
];

if (uniqueFindings.length > 0) {
  console.error("普通用户页面中文文案审计未通过：\n");
  for (const finding of uniqueFindings) {
    const relativeFile = path.relative(frontendRoot, finding.file).replaceAll("\\", "/");
    console.error(`- ${relativeFile}:${finding.location} ${finding.reason}：${finding.value}`);
  }
  process.exitCode = 1;
} else {
  console.log(`普通用户页面中文文案审计通过（已检查 ${files.length} 个页面与组件）。`);
}
