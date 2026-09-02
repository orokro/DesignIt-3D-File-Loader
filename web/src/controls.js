/**
 * First-person controls: fly by default, Tab toggles walk.
 *
 * Walk mode raycasts straight down onto the world to find the floor, applies
 * gravity, and allows a step-up so you can climb kerbs and stair treads
 * without jumping. The raycast is limited to nearby objects -- casting against
 * every merged mesh in a 340k-triangle world every frame is far too slow.
 */
import * as THREE from 'three';

const EYE = 66;          // inches -- roughly eye height for 5'8"
const STEP_UP = 9;       // inches a walker can climb without jumping
const GRAVITY = 900;     // in/s^2
const JUMP = 260;

export class Explorer {
  constructor(camera, dom) {
    this.camera = camera;
    this.dom = dom;
    this.yaw = 0; this.pitch = 0;
    this.vel = new THREE.Vector3();
    this.walk = false;
    this.grounded = false;
    this.speed = 260;              // in/s
    this.keys = new Set();
    this.ray = new THREE.Raycaster();
    this.ray.far = 4000;
    this.pickNearby = null;        // (pos) => Object3D[]
    this.onModeChange = null;

    dom.addEventListener('click', () => dom.requestPointerLock());
    document.addEventListener('pointerlockchange', () => {
      this.locked = document.pointerLockElement === dom;
    });
    document.addEventListener('mousemove', (e) => {
      if (!this.locked) return;
      // The camera looks along (sin yaw, cos yaw, ...) with +Z up, so its
      // screen-right vector is (cos yaw, -sin yaw, 0) -- which is exactly
      // d(direction)/d(yaw). Increasing yaw therefore swings the view to the
      // right, so a rightward mouse movement must ADD to it.
      this.yaw += e.movementX * 0.0022;
      this.pitch -= e.movementY * 0.0022;
      const lim = Math.PI / 2 - 0.02;
      this.pitch = Math.max(-lim, Math.min(lim, this.pitch));
    });
    addEventListener('keydown', (e) => {
      if (e.code === 'Tab') { e.preventDefault(); this.setWalk(!this.walk); return; }
      this.keys.add(e.code);
      if (['Space', 'ShiftLeft', 'ControlLeft'].includes(e.code)) e.preventDefault();
    });
    addEventListener('keyup', (e) => this.keys.delete(e.code));
    addEventListener('blur', () => this.keys.clear());
  }

  setWalk(on) {
    this.walk = on;
    this.vel.set(0, 0, 0);
    if (this.onModeChange) this.onModeChange(on);
  }

  teleport(x, y, z) {
    this.camera.position.set(x, y, z);
    this.vel.set(0, 0, 0);
  }

  update(dt) {
    dt = Math.min(dt, 0.05);
    const k = this.keys;
    const sprint = k.has('ShiftLeft') || k.has('ShiftRight') ? 3.2 : 1;

    // forward/right on the ground plane (Z is up)
    const f = new THREE.Vector3(Math.sin(this.yaw), Math.cos(this.yaw), 0);
    const r = new THREE.Vector3(Math.cos(this.yaw), -Math.sin(this.yaw), 0);
    const wish = new THREE.Vector3();
    if (k.has('KeyW')) wish.add(f);
    if (k.has('KeyS')) wish.sub(f);
    if (k.has('KeyD')) wish.add(r);
    if (k.has('KeyA')) wish.sub(r);
    if (wish.lengthSq()) wish.normalize();

    const p = this.camera.position;
    if (!this.walk) {
      let up = 0;
      if (k.has('Space')) up += 1;
      if (k.has('ControlLeft') || k.has('KeyC')) up -= 1;
      const s = this.speed * sprint * dt;
      p.addScaledVector(wish, s);
      p.z += up * s;
    } else {
      const s = this.speed * (sprint > 1 ? 1.8 : 1) * dt;
      p.addScaledVector(wish, s);
      this.vel.z -= GRAVITY * dt;
      p.z += this.vel.z * dt;
      const floor = this.floorUnder(p);
      if (floor !== null) {
        const target = floor + EYE;
        if (p.z <= target + STEP_UP && this.vel.z <= 0) {
          p.z = target;
          this.vel.z = 0;
          this.grounded = true;
        } else this.grounded = false;
      } else {
        this.grounded = false;
        if (p.z < -600) { p.z = 400; this.vel.z = 0; }   // fell off the world
      }
      if (this.grounded && k.has('Space')) { this.vel.z = JUMP; this.grounded = false; }
    }

    const dir = new THREE.Vector3(
      Math.sin(this.yaw) * Math.cos(this.pitch),
      Math.cos(this.yaw) * Math.cos(this.pitch),
      Math.sin(this.pitch));
    this.camera.lookAt(p.clone().add(dir));
  }

  /** World z of the surface under the camera, or null. */
  floorUnder(p) {
    if (!this.pickNearby) return 0;
    const objs = this.pickNearby(p);
    if (!objs.length) return null;
    this.ray.set(new THREE.Vector3(p.x, p.y, p.z + 4), new THREE.Vector3(0, 0, -1));
    const hits = this.ray.intersectObjects(objs, false);
    return hits.length ? hits[0].point.z : null;
  }
}
