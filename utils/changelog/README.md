## Generate changelog

Generate github token:
* https://github.com/settings/tokens - keep all checkboxes unchecked, no scopes need to be enabled.

Dependencies:
```
 apt-get install git curl jq python3 python3-fuzzywuzzy 
```


Usage example:

```
export GITHUB_USER=... GITHUB_TOKEN=ghp_...
./changelog.sh v21.5.6.6-stable v21.6.2.7-prestable
```
