echo "Configuring Git to handle line endings..."
if ! git config --global core.eol|grep -q "lf";then
git config --global core.eol lf
fi
if ! git config --global core.autocrlf|grep -q "input";then
git config --global core.autocrlf input
fi
echo "Git configuration complete."
echo "Creating or updating .gitattributes to enforce LF line endings..."
if [ ! -f .gitattributes ];then
echo "* text=auto eol=lf" >.gitattributes
echo ".gitattributes file created."
else
if ! grep -q "text=auto eol=lf" .gitattributes;then
echo "* text=auto eol=lf" >>.gitattributes
echo ".gitattributes file updated."
else
echo ".gitattributes file already contains the required settings."
fi
fi
echo "Converting CRLF to LF in all text files, excluding .git directory, bat files, and binary files..."
find . -type f ! -path '*/.git/*' ! -name '*.bat' ! -name '*.bin' ! -path '*/lib/*' ! -path '*/dist/*' ! -path '*/win/*' ! -path '*/node_modules/*'|while read -r file;do
if file "$file"|grep -q text;then
sed -i 's/\r$//' "$file"
echo "Converted line endings in: $file"
fi
done
