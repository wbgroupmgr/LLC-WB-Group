# LLC-WB-Group
Repository for LLC W&amp;B Group documents and code

[Getting Started](GettingStarted_Rental_LLC.md)


## Using Git to host website
(Google: how to create a website in github)

Creating a website on GitHub typically involves using GitHub Pages, a feature that allows you to host static websites directly from your GitHub repositories.

## Steps to create a website on GitHub Pages:
### 1. Create a GitHub Account:
- If you do not already have one, sign up for a free GitHub account.

### 2. Create a New Repository:
- Log in to your GitHub account.
- Click on the "New" button on your dashboard to create a new repository.
- For a `personal` or `organization` website:
    - Name the repository username.github.io
    - (replace username with your GitHub username or organization name).
    - This naming convention automatically sets up a user or organization site.
- For a `project website`: You can name the repository anything you like.
- Choose whether the repository should be public or private. GitHub Pages sites are publicly available even if the repository is private, depending on your plan. 
- Optionally, initialize the repository with a README.md file.

### 3. Add Your Website Files:
- `Upload directly`: You can drag and drop your website files (HTML, CSS, JavaScript, images, etc.) directly into the repository through the GitHub website interface.
- `Clone and Push`: Clone the repository to your local machine, add your website files to the local repository folder, and then commit and push the changes back to GitHub.

### 4. Configure GitHub Pages:
- Navigate to your repository on GitHub.
- Click on the "Settings" tab.
- In the sidebar, click on "Pages" under "Code and automation."
- Under "Build and deployment," choose "Deploy from a branch" as the source.
- Select the branch containing your website files (e.g., main or gh-pages) and the folder if your files are in a specific subfolder (e.g., /docs).
- Click "Save."

### 5. View Your Website:
- After configuring GitHub Pages, it may take a few minutes for the site to deploy.
- The URL for your website will be displayed in the "Pages" settings. For user/organization sites, it will be username.github.io. For project sites, it will be username.github.io/repository-name.
- You can also optionally configure a custom domain for your GitHub Pages site.

Note: GitHub Pages primarily supports static websites. This means you cannot directly host dynamic server-side applications or databases on GitHub Pages. For dynamic content, you would need to use a different hosting solution or integrate with external services.
