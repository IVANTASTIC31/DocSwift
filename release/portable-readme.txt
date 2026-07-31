DocSwift Windows portable package
=================================

1. Extract the whole zip file to a new folder.
2. Double-click DocSwift.exe.
3. Do not run the executable from inside the zip file.

Task data is stored in %LOCALAPPDATA%\DocSwift and is not included in this
package. Upgrading to a new folder therefore keeps unfinished review work.

The in-app "Check for updates" button checks the company update server first.
It only installs a package whose file size and SHA-256 digest can be verified.
Portable builds update in place, restart automatically, and restore the
previous version if the new application cannot start successfully.
