# 目录清理说明

## 当前状态

外层目录还保留了一些旧目录和文件：

```
E:\trading\
├── reports/          # 旧的报告目录
├── scripts/          # 旧的脚本目录  
└── 操作手册/         # 旧的文档目录
```

## 清理建议

### 1. reports/ 目录

**如果有旧报告**:
```bash
# 移动旧报告到新位置
cd E:\trading
mv reports/*.md stock_analysis/reports/ 2>/dev/null
# 删除空目录
rmdir reports
```

**如果是空目录**:
```bash
rmdir reports
```

### 2. scripts/ 目录

**已清空（旧脚本已移至 stock_analysis/legacy/）**:
```bash
# 删除空目录
cd E:\trading
rmdir scripts
```

### 3. 操作手册/ 目录

**保留或复制模板**:
```bash
# 方式1: 复制模板文件后删除
cp 操作手册/stock_analysis_template.md stock_analysis/docs/
rm -rf 操作手册

# 方式2: 如果还有其他有用文档，保留此目录
# 或移动整个目录到 stock_analysis/docs/
mv 操作手册 stock_analysis/docs/操作手册
```

### 4. stock/ 目录

**根据实际情况处理**:
- 如果不再使用：删除或归档
- 如果还有用：保持原样

## 一键清理命令

```bash
cd E:\trading

# 1. 移动reports下的报告文件
mv reports/*.md stock_analysis/reports/ 2>/dev/null

# 2. 删除空的reports目录
rmdir reports 2>/dev/null

# 3. 删除空的scripts目录  
rmdir scripts 2>/dev/null

# 4. 复制模板文件
cp 操作手册/stock_analysis_template.md stock_analysis/docs/ 2>/dev/null

# 5. (可选) 删除操作手册目录
# rm -rf 操作手册

echo "清理完成！"
```

## 清理后的目录结构

```
E:\trading\
├── stock_analysis/      ✅ 技术分析（所有内容已归类）
│   ├── core/
│   ├── datasources/
│   ├── legacy/         # 旧脚本
│   ├── reports/        # 报告输出
│   ├── docs/           # 文档模板
│   └── ...
│
├── stock_selector/      ✅ 条件选股
│
├── project/            ✅ 实战项目
│   └── stock/
│
└── .git/               # Git仓库
```

**清理后只保留三个主要模块，结构清晰！**
