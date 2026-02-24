const fs = require('fs');
let content = fs.readFileSync('public/index.html', 'utf8');
content = content.replace(/  <script>\r?\n\s+\(\(\) => \{[\s\S]*?\}\)\(\);\r?\n\s+<\/script>\r?\n/g, '');
fs.writeFileSync('public/index.html', content);
