#!/bin/sh
# Run from a reviewed root-owned source directory; never changes nginx or its marker.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
unset ENV BASH_ENV CDPATH

fail() { printf '%s\n' "$1" >&2; exit 1; }
[ "$(/usr/bin/id -u)" -eq 0 ] || fail 'Maintenance control installation requires root.'
[ "$#" -eq 0 ] || fail 'This installer accepts no arguments.'

source_dir=$(cd -- "$(/usr/bin/dirname -- "$0")" && pwd -P)
helper_source=$source_dir/deeplinkerp-main-maintenance
sudoers_source=$source_dir/deeplinkerp-main-maintenance.sudoers
helper=/usr/local/sbin/deeplinkerp-main-maintenance
sudoers=/etc/sudoers.d/deeplinkerp-main-maintenance
marker=/run/deeplinkerp-main-maintenance.on

[ ! -e "$marker" ] && [ ! -L "$marker" ] || fail 'Install only while maintenance is off.'
for directory in /usr/local/sbin /etc/sudoers.d; do
    [ -d "$directory" ] && [ ! -L "$directory" ] || fail "Unexpected installation directory: $directory"
done
for file in "$helper_source" "$sudoers_source"; do
    [ -f "$file" ] && [ ! -L "$file" ] || fail "Unexpected source: $file"
    [ "$(/usr/bin/stat -c '%u:%g' "$file")" = 0:0 ] || fail "Source must be root-owned: $file"
    mode=$(/usr/bin/stat -c '%a' "$file")
    [ "$((0$mode & 022))" -eq 0 ] || fail "Source must not be writable by group or others: $file"
done

check_existing() {
    if [ -e "$1" ] || [ -L "$1" ]; then
        [ -f "$1" ] && [ ! -L "$1" ] || fail "Unexpected installed target: $1"
        [ "$(/usr/bin/stat -c '%u:%g:%a' "$1")" = "0:0:$3" ] &&
            /usr/bin/cmp -s -- "$1" "$2" || fail "Refusing to overwrite installed target: $1"
    fi
}
check_existing "$helper" "$helper_source" 755
check_existing "$sudoers" "$sudoers_source" 440
/bin/sh -n "$helper_source"
/usr/sbin/visudo -cf "$sudoers_source"
/usr/sbin/visudo -c

new_helper=0
new_sudoers=0
rollback() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ "$result" -ne 0 ]; then
        if [ "$new_sudoers" -eq 1 ]; then /bin/rm -f -- "$sudoers"; fi
        if [ "$new_helper" -eq 1 ]; then /bin/rm -f -- "$helper"; fi
    fi
    exit "$result"
}
trap rollback EXIT
trap 'exit 1' HUP INT TERM
if [ ! -e "$helper" ]; then
    new_helper=1
    /usr/bin/install -o 0 -g 0 -m 0755 -- "$helper_source" "$helper"
fi
if [ ! -e "$sudoers" ]; then
    new_sudoers=1
    /usr/bin/install -o 0 -g 0 -m 0440 -- "$sudoers_source" "$sudoers"
fi
/usr/sbin/visudo -c
printf '%s\n' 'Installed host maintenance control; maintenance remains off.'
