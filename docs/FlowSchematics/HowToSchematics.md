# HowTo mmd/mmdc to svg 

The official tool to convert Mermaid () files to SVG 

from the command line is mermaid-js/mermaid-cli, which provides the  executable. [1, 2]  

## .mmd (Mermaid File)

- What it is: A plain text file containing the domain-specific language used to write diagrams like flowcharts, sequence diagrams, and mind maps.
- Purpose: It functions as "diagrams-as-code," allowing you to describe visuals easily.
- Usage:
    - You can write .mmd content inside dedicated Mermaid files o
    - embed it directly into standard .md (Markdown) files using
    - ```mermaid code blocks

## .mmdc (Mermaid CLI)

- What it is: The official command-line tool (Mermaid CLI) used to process your diagram code.
- Purpose: It takes an input file (like a .mmd or markdown file) and renders it into a visual format such as a .png, .svg, or .pdf.
- Usage: Typically run in a terminal or CI/CD pipeline, basic usage for image generation looks like this:

````mmdc -i input.mmd -o output.svg````


## Quick Conversion Command 
Once installed, use this single command to generate your vector image: [3]  

````
mmdc -i input.mmd -o output.svg

# Pipe 
cat diagram.mmd | mmdc -i - -o output.svg
````
 

## Option 1: Run via npx (No Installation Needed) 

If you have Node.js installed, you can execute the CLI immediately without a permanent installation: [3]  

````npx -p @mermaid-js/mermaid-cli mmdc -i input.mmd -o output.svg````


## Option 2: Local Installation (Recommended) 

Installing the tool locally within your project avoids common global permission conflicts: [3]  

# Install package
npm install @mermaid-js/mermaid-cli


````./node_modules/.bin/mmdc -i input.mmd -o output.svg````



[1] https://github.com/mermaid-js/mermaid-cli
[2] https://tessl.io/registry/tessl/npm-mermaid-js--mermaid-cli
[3] https://codesandbox.io/p/github/elicharlese/mermaid-cli
[4] https://github.com/orgs/mermaid-js/packages/container/package/mermaid-cli%2Fmermaid-cli
[5] https://mermaid2img.com/en-US/blog/another-way-to-convert-mermaid-to-img-for-developer
[6] https://www.npmjs.com/package/mermaid.cli
[7] https://ulfschneider.io/tools/mermaid-cli-batch/

