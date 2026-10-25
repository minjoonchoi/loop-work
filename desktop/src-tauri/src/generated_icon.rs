// Generated files never overwrite an existing user file or follow a symlink.
use std::os::{
    fd::{AsRawFd, FromRawFd},
    unix::fs::OpenOptionsExt,
};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::Path,
};
pub fn ensure_icon(root: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let directory = root.join("icons");
    match fs::symlink_metadata(&directory) {
        Ok(m) if m.file_type().is_dir() => (),
        Ok(_) => {
            return Err(std::io::Error::other(
                "Generated icon directory is not a real directory; preserved",
            ))
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => fs::create_dir(&directory)?,
        Err(e) => return Err(e),
    }
    let dir = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(&directory)?;
    let name = c"icon.png";
    let raw = unsafe {
        libc::openat(
            dir.as_raw_fd(),
            name.as_ptr(),
            libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_NONBLOCK,
        )
    };
    if raw >= 0 {
        let file = unsafe { File::from_raw_fd(raw) };
        if !file.metadata()?.is_file() {
            return Err(std::io::Error::other(
                "Generated icon path is not a regular file; preserved",
            ));
        }
        let mut old = Vec::new();
        file.take(bytes.len() as u64 + 1).read_to_end(&mut old)?;
        if old != bytes {
            return Err(std::io::Error::other(
                "User-modified generated icon preserved",
            ));
        }
        return Ok(());
    }
    let error = std::io::Error::last_os_error();
    if error.kind() != std::io::ErrorKind::NotFound {
        return Err(error);
    }
    let raw = unsafe {
        libc::openat(
            dir.as_raw_fd(),
            name.as_ptr(),
            libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_NOFOLLOW,
            0o644,
        )
    };
    if raw < 0 {
        return Err(std::io::Error::last_os_error());
    }
    let mut file = unsafe { File::from_raw_fd(raw) };
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
